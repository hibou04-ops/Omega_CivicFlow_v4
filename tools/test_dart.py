import httpx, asyncio, json

KEY = "173670325e93bb40adb1d3c59457f326727dd139"

async def main():
    async with httpx.AsyncClient(timeout=10.0) as c:
        # 1) company.json
        r1 = await c.get("https://opendart.fss.or.kr/api/company.json",
                         params={"crtfc_key": KEY, "corp_name": "삼성전자"})
        print("=== company.json ===")
        print(json.dumps(r1.json(), ensure_ascii=False, indent=2))

        # 2) list.json with corp_name (지원 여부 테스트)
        r2 = await c.get("https://opendart.fss.or.kr/api/list.json",
                         params={"crtfc_key": KEY, "corp_name": "삼성전자",
                                 "page_no": "1", "page_count": "5"})
        d2 = r2.json()
        print("\n=== list.json (corp_name) ===")
        print("status:", d2.get("status"), "total:", d2.get("total_count"))
        for item in d2.get("list", [])[:3]:
            print(item.get("corp_name"), "|", item.get("report_nm"), "|", item.get("rcept_dt"))

        # 3) list.json with corp_code (삼성전자 = 00126380)
        r3 = await c.get("https://opendart.fss.or.kr/api/list.json",
                         params={"crtfc_key": KEY, "corp_code": "00126380",
                                 "page_no": "1", "page_count": "5"})
        d3 = r3.json()
        print("\n=== list.json (corp_code 00126380) ===")
        print("status:", d3.get("status"), "total:", d3.get("total_count"))
        for item in d3.get("list", [])[:3]:
            print(item.get("corp_name"), "|", item.get("report_nm"), "|", item.get("rcept_dt"))

asyncio.run(main())
