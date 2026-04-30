import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
sys.stdout.reconfigure(encoding='utf-8')

for name in ["pending_docs.json", "pending_docs_all.json"]:
    fp = os.path.join(r"C:\Users\hibou\Downloads", name)
    if not os.path.exists(fp):
        print(f"❌ {name}: 파일 없음")
        continue
    
    sz = os.path.getsize(fp)
    print(f"\n{'='*50}")
    print(f"📄 {name} ({sz//1048576}MB)")
    
    try:
        with open(fp, "r", encoding="utf-8") as f:
            d = json.load(f)
        print(f"  ✅ JSON 파싱 OK: {len(d)}건")
        
        # 필드 체크
        if d:
            keys = set(d[0].keys())
            print(f"  필드: {keys}")
        
        # 텍스트 품질
        empty = 0
        short = 0
        good = 0
        very_long = 0
        max_len = 0
        for item in d:
            tl = item.get("text_len", 0)
            txt = item.get("text", "")
            actual_len = len(txt)
            if actual_len < 10:
                empty += 1
            elif actual_len < 100:
                short += 1
            else:
                good += 1
            if actual_len > 100000:
                very_long += 1
            max_len = max(max_len, actual_len)
        
        print(f"  빈 텍스트(<10자): {empty}건")
        print(f"  매우 짧은(<100자): {short}건")
        print(f"  정상(≥100자): {good}건")
        print(f"  초장문(>100K자): {very_long}건")
        print(f"  최대 길이: {max_len:,}자")
        
        # 샘플
        print(f"\n  샘플 1: id={d[0].get('doc_id')} fn={d[0].get('filename','')[:50]} len={len(d[0].get('text',''))}")
        print(f"  샘플 끝: id={d[-1].get('doc_id')} fn={d[-1].get('filename','')[:50]} len={len(d[-1].get('text',''))}")
        
        # 텍스트 내용 샘플
        for item in d[:3]:
            txt = item.get("text", "")[:100]
            print(f"  내용미리보기: {txt}")
            
    except json.JSONDecodeError as e:
        print(f"  ❌ JSON 파싱 실패: {e}")
    except Exception as e:
        print(f"  ❌ 오류: {e}")
