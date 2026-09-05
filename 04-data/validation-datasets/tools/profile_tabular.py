from process_all import profile_tabular

if __name__ == "__main__":
    rows = profile_tabular()
    print(f"profiled {len(rows)} tabular source sheets")
