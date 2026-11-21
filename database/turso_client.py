import os
import requests
from typing import List, Dict, Any, Optional

class TursoClient:
    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        raw_url = url or os.environ.get("TURSO_DATABASE_URL", "")
        # تحويل الرابط إلى HTTPS مع مسار الـ pipeline
        clean_url = raw_url.replace("libsql://", "https://").rstrip("/")
        if not clean_url.endswith("/v2/pipeline"):
            clean_url = clean_url + "/v2/pipeline"
        self.endpoint = clean_url
        self.token = token or os.environ.get("TURSO_AUTH_TOKEN", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.token and "turso.io" in self.endpoint)

    def execute(self, sql: str, params: Optional[List[Any]] = None) -> Dict[str, Any]:
        """تنفيذ أمر SQL فردي"""
        return self.execute_batch([(sql, params or [])])[0]

    def execute_batch(self, statements: List[tuple]) -> List[Dict[str, Any]]:
        """تنفيذ مجموعة أوامر SQL في طلب واحد سريع (Batch Pipeline)"""
        if not self.is_configured:
            return []

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        requests_payload = []
        for stmt in statements:
            if isinstance(stmt, str):
                sql_str = stmt
                p_list = []
            else:
                sql_str, p_list = stmt

            args_payload = []
            for val in p_list:
                if val is None:
                    args_payload.append({"type": "null"})
                elif isinstance(val, int):
                    args_payload.append({"type": "integer", "value": str(val)})
                elif isinstance(val, float):
                    args_payload.append({"type": "float", "value": val})
                else:
                    args_payload.append({"type": "text", "value": str(val)})

            requests_payload.append({
                "type": "execute",
                "stmt": {
                    "sql": sql_str,
                    "args": args_payload
                }
            })

        resp = requests.post(
            self.endpoint,
            headers=headers,
            json={"requests": requests_payload},
            timeout=60
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Turso API Error ({resp.status_code}): {resp.text}")

        data = resp.json()
        results = []
        for item in data.get("results", []):
            if item.get("type") == "ok":
                res = item.get("response", {}).get("result", {})
                cols = [c["name"] for c in res.get("cols", [])]
                rows = []
                for r in res.get("rows", []):
                    row_vals = []
                    for cell in r:
                        if cell.get("type") == "null":
                            row_vals.append(None)
                        elif cell.get("type") == "integer":
                            row_vals.append(int(cell.get("value", 0)))
                        elif cell.get("type") == "float":
                            row_vals.append(float(cell.get("value", 0.0)))
                        else:
                            row_vals.append(cell.get("value", ""))
                    rows.append(dict(zip(cols, row_vals)))
                results.append({"cols": cols, "rows": rows, "affected": res.get("affected_row_count", 0)})
            else:
                raise RuntimeError(f"Turso execution error: {item}")

        return results

    def query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """تنفيذ استعلام SELECT واسترجاع النتائج كـ قائمة قواميس"""
        res = self.execute(sql, params)
        return res.get("rows", [])

turso = TursoClient()
