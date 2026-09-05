from process_all import build_master

if __name__ == "__main__":
    out, total, selected = __import__("process_all").extract_osha()
    records, narratives = build_master(out, 0)
    print(f"normalized master rows={records}; narrative rows={narratives}")
