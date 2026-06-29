"""Join barrier state for fork/join parallel branches."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Optional

JOIN_NODE_TYPES = frozenset({"joinAllNode", "joinAnyNode"})
FORK_NODE_TYPE = "forkNode"
IF_NODE_TYPE = "ifNode"
SWITCH_NODE_TYPE = "switchNode"
EXCLUSIVE_BRANCH_NODE_TYPES = frozenset({IF_NODE_TYPE, SWITCH_NODE_TYPE})


@dataclass
class JoinBarrier:
    mode: str
    expected: FrozenSet[str]
    arrived: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    fired: bool = False
    winner_id: Optional[str] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


def snapshot_node_outputs(chain: Any, node_id: str) -> Dict[str, Any]:
    prefix = f"{node_id}."
    result: Dict[str, Any] = {}
    for key, value in chain.memory.items():
        if key.startswith(prefix):
            result[key[len(prefix):]] = value
    return result


def branch_success(snapshot: Dict[str, Any]) -> bool:
    success = snapshot.get("success")
    if success is None:
        return True
    if isinstance(success, bool):
        return success
    return str(success).lower() in ("true", "1")


def _build_join_result(
    barrier: JoinBarrier,
    mode: str,
    joined: bool,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "joined": joined,
        "skipped": False,
        "mode": mode,
        "branchCount": len(barrier.arrived),
        "results": dict(barrier.arrived),
    }
    if mode == "any":
        result["winnerNodeId"] = barrier.winner_id or ""
    if error:
        result["errorMessage"] = error
        result["failed"] = not joined
    else:
        result["failed"] = False
    return result


def handle_join_arrival(
    chain: Any,
    join_node_id: str,
    mode: str,
    source_id: str,
) -> Dict[str, Any]:
    barrier = chain._join_barriers.get(join_node_id)
    if barrier is None:
        return {"joined": False, "skipped": True, "mode": mode}

    if not source_id:
        return {"joined": False, "skipped": False, "mode": mode, "branchCount": 0}

    with barrier.lock:
        if barrier.fired:
            return {"joined": False, "skipped": True, "mode": mode}

        snapshot = snapshot_node_outputs(chain, source_id)
        barrier.arrived[source_id] = snapshot

        if mode == "any":
            if branch_success(snapshot):
                barrier.fired = True
                barrier.winner_id = source_id
                return _build_join_result(barrier, mode, joined=True)

            if barrier.expected and len(barrier.arrived) >= len(barrier.expected):
                barrier.fired = True
                return _build_join_result(
                    barrier,
                    mode,
                    joined=False,
                    error="所有并行分支均未成功",
                )
            return {
                "joined": False,
                "skipped": False,
                "mode": mode,
                "branchCount": len(barrier.arrived),
                "failed": False,
            }

        if len(barrier.arrived) < len(barrier.expected):
            return {
                "joined": False,
                "skipped": False,
                "mode": mode,
                "branchCount": len(barrier.arrived),
                "failed": False,
            }

        failed = [
            sid for sid, snap in barrier.arrived.items() if not branch_success(snap)
        ]
        barrier.fired = True
        if failed:
            return _build_join_result(
                barrier,
                mode,
                joined=False,
                error=f"分支执行失败: {', '.join(failed)}",
            )
        return _build_join_result(barrier, mode, joined=True)


def init_join_barriers(chain: Any) -> None:
    barriers: Dict[str, JoinBarrier] = {}
    for node in chain.nodes:
        if node.node_type not in JOIN_NODE_TYPES:
            continue
        expected = frozenset(
            edge.source for edge in node.inward_edges if edge.source
        )
        mode = "all" if node.node_type == "joinAllNode" else "any"
        barriers[node.id] = JoinBarrier(mode=mode, expected=expected)
    chain._join_barriers = barriers
