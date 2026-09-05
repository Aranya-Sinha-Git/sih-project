from process_all import extract_osha

if __name__ == "__main__":
    out, total, selected = extract_osha()
    print(f"OSHA rows={total}; oil-gas candidates={selected}; output={out}")
