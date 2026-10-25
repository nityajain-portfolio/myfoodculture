"""Load the Jain Restaurant Directory spreadsheet into the jain_restaurants table.

Usage: python import_restaurants.py ["Jain Restaurant Directory.xlsx"]

Re-running replaces all rows in jain_restaurants with the spreadsheet contents.
"""
import os
import re
import sys

import mysql.connector
import openpyxl
from dotenv import load_dotenv

load_dotenv()

DEFAULT_FILE = 'Jain Restaurant Directory.xlsx'

CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS jain_restaurants (
        id INT NOT NULL AUTO_INCREMENT,
        continent VARCHAR(50),
        country VARCHAR(100),
        city VARCHAR(100),
        name VARCHAR(255) NOT NULL,
        cuisine VARCHAR(100),
        place_type VARCHAR(50),
        jain_options VARCHAR(100),
        price VARCHAR(10),
        address VARCHAR(500),
        postal_code VARCHAR(20),
        maps_url TEXT,
        notes TEXT,
        PRIMARY KEY (id),
        KEY idx_country (country),
        KEY idx_postal_code (postal_code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
"""

# Postal code formats by country. The last match in the address wins, so
# street numbers earlier in the address aren't mistaken for postal codes.
POSTAL_PATTERNS = {
    'United States': r'\b\d{5}(?:-\d{4})?\b',
    'Canada': r'\b[A-Z]\d[A-Z] ?\d[A-Z]\d\b',
    'United Kingdom': r'\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b',
    'Netherlands': r'\b\d{4} ?[A-Z]{2}\b',
    'Japan': r'\b\d{3}-\d{4}\b',
    'Argentina': r'\b[A-Z]\d{4}[A-Z]{0,3}\b',
    'India': r'\b\d{6}\b',
    'Singapore': r'\b\d{6}\b',
    'China': r'\b\d{6}\b',
    'Mexico': r'\b\d{5}\b',
    'France': r'\b\d{5}\b',
    'Germany': r'\b\d{5}\b',
    'Italy': r'\b\d{5}\b',
    'Indonesia': r'\b\d{5}\b',
    'Thailand': r'\b\d{5}\b',
    'Australia': r'\b\d{4}\b',
    'Austria': r'\b\d{4}\b',
    'Switzerland': r'\b\d{4}\b',
    'New Zealand': r'\b\d{4}\b',
    'South Africa': r'\b\d{4}\b',
}

HYPERLINK_RE = re.compile(r'=HYPERLINK\("([^"]+)"', re.IGNORECASE)


def extract_postal_code(country, address):
    if not country or not address:
        return None
    # "United Kingdom - England" -> "United Kingdom"
    pattern = POSTAL_PATTERNS.get(country.split(' - ')[0])
    if not pattern:
        return None
    # re.ASCII keeps \d from matching full-width digits in Japanese/Thai addresses
    matches = re.findall(pattern, address, re.ASCII)
    return matches[-1] if matches else None


def extract_maps_url(value):
    if not value:
        return None
    match = HYPERLINK_RE.match(str(value))
    return match.group(1) if match else str(value)


def clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def read_restaurants(path):
    workbook = openpyxl.load_workbook(path, read_only=True)
    rows = workbook.active.iter_rows(values_only=True)
    next(rows)  # header row

    restaurants = []
    for row in rows:
        (continent, country, city, name, cuisine, place_type,
         jain_options, price, address, maps_link, notes) = (list(row) + [None] * 11)[:11]
        name = clean(name)
        if not name:
            continue  # blank rows
        country = clean(country)
        address = clean(address)
        restaurants.append((
            clean(continent), country, clean(city), name, clean(cuisine), clean(place_type),
            clean(jain_options), clean(price), address, extract_postal_code(country, address),
            extract_maps_url(maps_link), clean(notes),
        ))
    workbook.close()
    return restaurants


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE
    print(f"📄 Reading {path}...")
    restaurants = read_restaurants(path)
    with_postal = sum(1 for r in restaurants if r[9])
    print(f"✅ Found {len(restaurants)} restaurants ({with_postal} with a postal code)")

    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )
    cursor = conn.cursor()
    cursor.execute(CREATE_TABLE_SQL)
    cursor.execute("DELETE FROM jain_restaurants")
    cursor.executemany("""
        INSERT INTO jain_restaurants (continent, country, city, name, cuisine, place_type,
                                      jain_options, price, address, postal_code, maps_url, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, restaurants)
    conn.commit()
    cursor.close()
    conn.close()
    print(f"✅ Loaded {len(restaurants)} restaurants into jain_restaurants")


if __name__ == '__main__':
    main()
