from process_all import verify_files

if __name__ == "__main__":
    rows = verify_files()
    print(f"verified {len(rows)} source files")
