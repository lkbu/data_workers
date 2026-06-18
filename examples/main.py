from core.workers.pko_scraper import get_5_year_fixed_base_rate, get_wibor_wibid_rates


def main():
    print("Hello from data-workers!")

    date_result, rate_result = get_5_year_fixed_base_rate("2026-03-31")
    if date_result:
        print("Found '5-letnia stała stopa bazowa':")
        print(f"Date: {date_result}")
        print(f"Rate: {rate_result}")

    print("-" * 40)
    w_date, wibid_df, wibor_df = get_wibor_wibid_rates("2026-03-31")
    if w_date:
        print(f"WIBOR/WIBID Data from dropdown date: Z dnia {w_date}")
        print("\nWIBID Table:")
        print(wibid_df.to_string(index=False))
        print("\nWIBOR Table:")
        print(wibor_df.to_string(index=False))
    print("-" * 40)


if __name__ == "__main__":
    main()
