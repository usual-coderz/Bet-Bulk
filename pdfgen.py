from fpdf import FPDF


def build(rows: list[dict], site: str, job_id: str) -> tuple[str, str]:
    txt_path = f"/tmp/{job_id}.txt"
    pdf_path = f"/tmp/{job_id}.pdf"

    with open(txt_path, "w") as f:
        for r in rows:
            f.write(f"{r['username']}\t{r['password']}\t{r['mobile']}\n")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, f"{site} - accounts", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    pdf.cell(0, 6, f"job {job_id} | {len(rows)} accounts", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for r in rows:
        pdf.cell(0, 6, f"{r['username']}  |  {r['password']}  |  {r['mobile']}",
                 new_x="LMARGIN", new_y="NEXT")
    pdf.output(pdf_path)
    return txt_path, pdf_path