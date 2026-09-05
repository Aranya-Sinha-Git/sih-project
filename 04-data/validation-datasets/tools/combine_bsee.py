from process_all import combine_bsee

if __name__ == "__main__":
    out, rows = combine_bsee()
    print(f"BSEE rows={rows}; output={out}")
