"""
Kontrola kompletności Rejestru Systemów AI (Bank Przykładowy).

Czyta arkusz "Rejestr" z pliku Excel, sprawdza każdy system regułami K1–K7
z arkusza "Zasady" i zapisuje dwa raporty CSV:
  - braki_RRRR-MM-DD.csv   – lista wszystkich znalezionych braków,
  - status_RRRR-MM-DD.csv  – jeden wiersz na system: czy wpis jest kompletny.
Te same dane trafiają też do braki.csv i status.csv (stałe nazwy dla Power BI).

Uruchomienie:
  python kontrola_rejestru.py Rejestr_systemow_AI_Bank_Przykladowy.xlsx
"""

import sys
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook


# ---------------------------------------------------------------------------
# 1. Wczytanie danych
# ---------------------------------------------------------------------------

def wczytaj_rejestr(sciezka):
    """Zwraca tabelę z arkusza Rejestr (jeden wiersz = jeden system AI)."""
    rejestr = pd.read_excel(sciezka, sheet_name="Rejestr")
    # Pomijamy puste wiersze (bez ID)
    return rejestr.dropna(subset=["ID"])


def wczytaj_date_kontroli(sciezka):
    """Odczytuje datę kontroli z komórki Zasady!B3."""
    wb = load_workbook(sciezka, data_only=True)
    data = wb["Zasady"]["B3"].value
    if not isinstance(data, datetime):
        sys.exit("Brak daty kontroli w Zasady!B3. Otwórz i zapisz plik w Excelu, jeśli B3 zawiera formułę.")
    return pd.Timestamp(data)


def pusty(wartosc):
    """True, jeśli komórka jest pusta (brak wartości albo pusty tekst)."""
    return pd.isna(wartosc) or str(wartosc).strip() == ""


# ---------------------------------------------------------------------------
# 2. Reguły kontroli K1–K7
#    Każda reguła dostaje jeden wiersz rejestru (system) i datę kontroli.
#    Zwraca opis braku (tekst) albo None, gdy wszystko jest w porządku.
# ---------------------------------------------------------------------------

def k1_wlasciciel(s, data_kontroli):
    if pusty(s["Właściciel biznesowy"]):
        return "brak właściciela biznesowego"


def k2_klasyfikacja(s, data_kontroli):
    if pusty(s["Kategoria AI Act"]) or pusty(s["Istotność"]):
        return "brak klasyfikacji (kategoria AI Act lub istotność)"


def k3_przeglad(s, data_kontroli):
    termin = s["Następny przegląd"]
    if not pusty(termin) and pd.Timestamp(termin) < data_kontroli:
        return f"przegląd po terminie ({pd.Timestamp(termin):%d.%m.%Y})"


def k4_fria(s, data_kontroli):
    if s["FRIA wymagana"] == "Tak" and s["Status FRIA"] != "Wykonana":
        return f"wymagana FRIA nie wykonana (status: {s['Status FRIA']})"


def k5_dpia(s, data_kontroli):
    if s["DPIA wymagana"] == "Tak" and s["Status DPIA"] != "Wykonana":
        return f"wymagana DPIA nie wykonana (status: {s['Status DPIA']})"


def k6_walidacja(s, data_kontroli):
    sciezka = "" if pusty(s["Ścieżka kontroli"]) else str(s["Ścieżka kontroli"])
    if sciezka.startswith("Pełna walidacja") and s["Status walidacji"] != "Wykonana":
        return f"brak walidacji na pełnej ścieżce (status: {s['Status walidacji']})"


def k7_zakazane(s, data_kontroli):
    if s["Kategoria AI Act"] == "Zakazane" and s["Status cyklu życia"] != "Wycofany":
        return "praktyka zakazana w użyciu"


# Lista reguł: (ID, poziom, funkcja). Nową regułę dodajesz jedną linijką.
REGULY = [
    ("K1", "UWAGA",     k1_wlasciciel),
    ("K2", "KRYTYCZNE", k2_klasyfikacja),
    ("K3", "UWAGA",     k3_przeglad),
    ("K4", "KRYTYCZNE", k4_fria),
    ("K5", "KRYTYCZNE", k5_dpia),
    ("K6", "KRYTYCZNE", k6_walidacja),
    ("K7", "KRYTYCZNE", k7_zakazane),
]


# ---------------------------------------------------------------------------
# 3. Kontrola: każdy system przez każdą regułę
# ---------------------------------------------------------------------------

def kontroluj(rejestr, data_kontroli):
    braki = []
    for _, system in rejestr.iterrows():
        for id_reguly, poziom, regula in REGULY:
            opis = regula(system, data_kontroli)
            if opis:
                braki.append({
                    "ID": system["ID"],
                    "System": system["Nazwa systemu"],
                    "Właściciel": "" if pusty(system["Właściciel biznesowy"]) else system["Właściciel biznesowy"],
                    "Reguła": id_reguly,
                    "Poziom": poziom,
                    "Opis": opis,
                })
    return pd.DataFrame(braki, columns=["ID", "System", "Właściciel", "Reguła", "Poziom", "Opis"])


def status_systemow(rejestr, braki):
    """Jeden wiersz na system: liczba braków i czy wpis jest kompletny."""
    status = rejestr[["ID", "Nazwa systemu", "Kategoria AI Act", "Istotność"]].copy()
    liczba = braki.groupby("ID").size()
    status["Liczba braków"] = status["ID"].map(liczba).fillna(0).astype(int)
    status["Kompletny"] = status["Liczba braków"].apply(lambda n: "Tak" if n == 0 else "Nie")
    return status


# ---------------------------------------------------------------------------
# 4. Raport
# ---------------------------------------------------------------------------

def main():
    sciezka = sys.argv[1] if len(sys.argv) > 1 else "Rejestr_systemow_AI_Bank_Przykladowy.xlsx"

    rejestr = wczytaj_rejestr(sciezka)
    data_kontroli = wczytaj_date_kontroli(sciezka)

    braki = kontroluj(rejestr, data_kontroli)
    status = status_systemow(rejestr, braki)

    kompletne = (status["Kompletny"] == "Tak").sum()
    wszystkie = len(status)

    print(f"Kontrola rejestru systemów AI – {data_kontroli:%d.%m.%Y}")
    print(f"Sprawdzono: {wszystkie} systemów")
    print(f"Kompletne: {kompletne} ({kompletne / wszystkie:.0%})")
    print()
    # Najpierw braki krytyczne, potem uwagi ("KRYTYCZNE" < "UWAGA" alfabetycznie)
    for _, b in braki.sort_values(["Poziom", "ID"]).iterrows():
        print(f"[{b['Poziom']:<9}] {b['ID']} {b['System']} – {b['Opis']} ({b['Reguła']})")

    # CSV ze średnikiem i kodowaniem utf-8-sig: polski Excel otworzy je poprawnie
    dzien = f"{data_kontroli:%Y-%m-%d}"
    braki.to_csv(f"braki_{dzien}.csv", sep=";", index=False, encoding="utf-8-sig")
    status.to_csv(f"status_{dzien}.csv", sep=";", index=False, encoding="utf-8-sig")
    # Stałe nazwy: Power BI zawsze czyta najnowszą kontrolę
    braki.to_csv("braki.csv", sep=";", index=False, encoding="utf-8-sig")
    status.to_csv("status.csv", sep=";", index=False, encoding="utf-8-sig")
    print()
    print(f"Raporty zapisane: braki_{dzien}.csv, status_{dzien}.csv oraz braki.csv, status.csv")


if __name__ == "__main__":
    main()
