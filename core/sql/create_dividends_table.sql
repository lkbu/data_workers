-- Table: mdh.dividends
-- Stores Polish stock dividend data parsed from StockWatch.pl

CREATE SCHEMA IF NOT EXISTS mdh;

CREATE TABLE IF NOT EXISTS mdh.dividends (
    id BIGSERIAL PRIMARY KEY,
    dividend_year INT NOT NULL,
    company_name VARCHAR(100) NOT NULL,
    ticker_slug VARCHAR(50),
    period_from DATE,
    period_to DATE,
    status VARCHAR(30) NOT NULL,
    payment_date DATE,
    record_date DATE,
    ex_date DATE,
    agm_date DATE,
    dps NUMERIC(12, 4),
    currency VARCHAR(10) DEFAULT 'PLN',
    dividend_yield NUMERIC(6, 4),
    note VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast lookup and reconciliation by year and company
CREATE INDEX IF NOT EXISTS idx_dividends_year_company ON mdh.dividends (dividend_year, company_name);
