"""MyBatis SQL template rendering tests."""
from __future__ import annotations

import unittest

from src.flowgame.chain.mybatis_sql import (
    _eval_test,
    escape_pymysql_percent_literals,
    render_mybatis_sql,
)


class MybatisSqlTest(unittest.TestCase):
    def test_status_equality_if_blocks(self) -> None:
        template = """SELECT sku_id FROM goods_sku WHERE 1=1
<if test="status == '1'">
    AND audit_status = 1
</if>
<if test="status == '2'">
    AND audit_status = 0
</if>"""

        sql_one, _ = render_mybatis_sql(template, {"status": "1"})
        self.assertIn("audit_status = 1", sql_one)
        self.assertNotIn("audit_status = 0", sql_one)

        sql_two, _ = render_mybatis_sql(template, {"status": "2"})
        self.assertIn("audit_status = 0", sql_two)
        self.assertNotIn("audit_status = 1", sql_two)

    def test_like_modifier(self) -> None:
        template = "SELECT * FROM goods_sku WHERE goods_name LIKE #{keyword,like}"
        sql, binds = render_mybatis_sql(template, {"keyword": "苹果"})
        self.assertEqual(binds, ["%苹果%"])
        self.assertIn("LIKE %s", sql)

    def test_concat_percent_literal_escape(self) -> None:
        template = "SELECT * FROM goods_sku WHERE goods_name LIKE CONCAT('%', #{keyword}, '%')"
        sql, binds = render_mybatis_sql(template, {"keyword": "苹果"})
        self.assertEqual(binds, ["苹果"])
        self.assertIn("CONCAT('%%', %s, '%%')", sql)
        self.assertEqual(
            escape_pymysql_percent_literals("LIKE CONCAT('%', %s, '%')"),
            "LIKE CONCAT('%%', %s, '%%')",
        )

    def test_null_checks_still_work(self) -> None:
        self.assertTrue(_eval_test("companyId != null", {"companyId": 1}))
        self.assertFalse(_eval_test("companyId != null", {"companyId": None}))


if __name__ == "__main__":
    unittest.main()
