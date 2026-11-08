from pathlib import Path
from openpyxl import load_workbook
from fitcoach.config import MAX_EXCEL_BYTES
from fitcoach.db import add_knowledge

def import_excel(path: Path, coach_id: int):
    if path.stat().st_size > MAX_EXCEL_BYTES:
        raise ValueError("حجم فایل بیشتر از ۸ مگابایت است.")
    if path.suffix.lower() not in (".xlsx",".xlsm"):
        raise ValueError("فقط فایل Excel با پسوند xlsx یا xlsm پذیرفته می‌شود.")
    wb=load_workbook(path,read_only=True,data_only=True)
    count=0
    try:
        for ws in wb.worksheets:
            rows=ws.iter_rows(values_only=True)
            headers=None
            for idx,row in enumerate(rows, start=1):
                values=[str(v).strip() if v is not None else "" for v in row]
                if not any(values): continue
                if headers is None:
                    headers=[v.lower() for v in values]
                    # If first row is not a header, still import it as content.
                    if not any(h in headers for h in ("content","محتوا","متن","title","عنوان","category","دسته")):
                        headers=[f"column_{i+1}" for i in range(len(values))]
                    else:
                        continue
                data={headers[i] if i<len(headers) else f"column_{i+1}":v for i,v in enumerate(values) if v}
                category=next((v for k,v in data.items() if k in ("category","دسته","نوع")), "general")
                tags=next((v for k,v in data.items() if k in ("tags","برچسب","کلیدواژه")), "")
                content=" | ".join(f"{k}: {v}" for k,v in data.items())
                if content.strip():
                    add_knowledge(coach_id,path.name,ws.title,idx,category,content,tags)
                    count+=1
    finally:
        wb.close()
    return count
