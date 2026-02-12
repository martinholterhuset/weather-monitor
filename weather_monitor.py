#!/usr/bin/env python3
"""
Værvarsel script som bruker Met.no API
Varsler via Slack webhook ved:
- Store nedbørsmengder
- Farevarsler
- Store temperatursvingninger
"""

import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import time
import os
from pathlib import Path

# Last inn miljøvariabler fra .env fil (valgfritt)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv er ikke installert, fortsett uten

# ===== KONFIGURASJON =====
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "DIN_SLACK_WEBHOOK_URL_HER")

# Legg til dine destinasjoner med navn, breddegrad og lengdegrad
# Romerike-kommuner
LOCATIONS = [
    {"name": "Aurskog-Høland", "lat": 59.8831, "lon": 11.5617},
    {"name": "Eidsvoll", "lat": 60.3345, "lon": 11.2525},
    {"name": "Enebakk", "lat": 59.7631, "lon": 11.1542},
    {"name": "Hurdal", "lat": 60.4674, "lon": 11.0514},
    {"name": "Gjerdrum", "lat": 60.0833, "lon": 11.0333},
    {"name": "Lillestrøm", "lat": 59.9500, "lon": 11.2000},
    {"name": "Lørenskog", "lat": 59.9294, "lon": 10.9574},
    {"name": "Nannestad", "lat": 60.2261, "lon": 11.0236},
    {"name": "Nes (Akershus)", "lat": 60.1333, "lon": 11.4667},
    {"name": "Nittedal", "lat": 60.0500, "lon": 10.8667},
    {"name": "Ullensaker", "lat": 60.1333, "lon": 11.1667},
    {"name": "Rælingen", "lat": 59.9333, "lon": 11.0833},
]

# Terskelverdier for varsling
THRESHOLDS = {
    "nedbør_mm_per_time": float(os.getenv("THRESHOLD_PRECIPITATION_HOURLY", "5.0")),
    "nedbør_mm_per_dag": float(os.getenv("THRESHOLD_PRECIPITATION_DAILY", "30.0")),
    "temp_sving_grader": float(os.getenv("THRESHOLD_TEMPERATURE_SWING", "15.0")),
}

# User-Agent er påkrevd av Met.no API
USER_EMAIL = os.getenv("USER_EMAIL", "your.email@example.com")
HEADERS = {
    "User-Agent": f"WeatherMonitor/1.0 ({USER_EMAIL})"
}

# ===== HJELPEFUNKSJONER =====

def hent_værdata(lat: float, lon: float) -> Optional[Dict]:
    """Henter værdata fra Met.no Locationforecast API"""
    url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact"
    params = {"lat": lat, "lon": lon}
    
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Feil ved henting av værdata: {e}")
        return None


def hent_farevarsler_norge() -> Optional[Dict]:
    """Henter farevarsler fra Met.no MetAlerts API for hele Norge"""
    url = "https://api.met.no/weatherapi/metalerts/2.0/current.json"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Filtrer varsler som gjelder for Norge
        relevante_varsler = []
        sett_varsler = set()  # For å unngå duplikater
        
        if "features" in data:
            for feature in data["features"]:
                props = feature.get("properties", {})
                
                # Sjekk om varslet gjelder for Norge
                if props.get("county") or props.get("MunicipalityId"):
                    # Lag en unik nøkkel for varselet
                    varsel_id = f"{props.get('event', '')}_{props.get('severity', '')}_{props.get('onset', '')}"
                    
                    # Bare legg til hvis vi ikke har sett dette varselet før
                    if varsel_id not in sett_varsler:
                        sett_varsler.add(varsel_id)
                        relevante_varsler.append(feature)
        
        return {"features": relevante_varsler} if relevante_varsler else None
    except requests.exceptions.RequestException as e:
        print(f"Feil ved henting av farevarsler: {e}")
        return None


def analyser_nedbør(værdata: Dict) -> Dict[str, any]:
    """Analyserer nedbørsmengder fra værdata - ser på alle tilgjengelige data"""
    timeseries = værdata.get("properties", {}).get("timeseries", [])
    
    max_nedbør_time = 0.0
    total_nedbør = 0.0
    timer_med_data = 0
    
    # Gå gjennom ALLE tilgjengelige timepunkter (vanligvis 48-90 timer)
    for entry in timeseries:
        details = entry.get("data", {}).get("next_1_hours", {}).get("details", {})
        nedbør = details.get("precipitation_amount", 0.0)
        
        if nedbør is not None:
            max_nedbør_time = max(max_nedbør_time, nedbør)
            total_nedbør += nedbør
            timer_med_data += 1
    
    # Beregn også 24-timers total for sammenligning
    total_nedbør_24t = 0.0
    for entry in timeseries[:24]:
        details = entry.get("data", {}).get("next_1_hours", {}).get("details", {})
        nedbør = details.get("precipitation_amount", 0.0)
        if nedbør is not None:
            total_nedbør_24t += nedbør
    
    return {
        "max_per_time": max_nedbør_time,
        "total_24t": total_nedbør_24t,
        "total_periode": total_nedbør,
        "timer_dekket": timer_med_data
    }


def analyser_temperatur(værdata: Dict) -> Dict[str, any]:
    """Analyserer temperatursvingninger - ser på alle tilgjengelige data"""
    timeseries = værdata.get("properties", {}).get("timeseries", [])
    
    temperaturer_alle = []
    temperaturer_24t = []
    
    # Samle alle temperaturer
    for i, entry in enumerate(timeseries):
        instant = entry.get("data", {}).get("instant", {}).get("details", {})
        temp = instant.get("air_temperature")
        if temp is not None:
            temperaturer_alle.append(temp)
            if i < 24:
                temperaturer_24t.append(temp)
    
    if not temperaturer_alle:
        return {"min": 0, "max": 0, "sving": 0, "min_24t": 0, "max_24t": 0, "sving_24t": 0, "timer_dekket": 0}
    
    # Beregn for hele perioden
    min_temp = min(temperaturer_alle)
    max_temp = max(temperaturer_alle)
    sving = max_temp - min_temp
    
    # Beregn for 24 timer
    min_temp_24t = min(temperaturer_24t) if temperaturer_24t else 0
    max_temp_24t = max(temperaturer_24t) if temperaturer_24t else 0
    sving_24t = max_temp_24t - min_temp_24t if temperaturer_24t else 0
    
    return {
        "min": min_temp,
        "max": max_temp,
        "sving": sving,
        "min_24t": min_temp_24t,
        "max_24t": max_temp_24t,
        "sving_24t": sving_24t,
        "timer_dekket": len(temperaturer_alle)
    }


def send_slack_varsel(melding: str, lokasjon: str, alvorlighetsgrad: str = "warning"):
    """Sender varsel til Slack via webhook med knapp til Met.no"""
    
    # Finn koordinater for lokasjonen
    lat, lon = None, None
    for loc in LOCATIONS:
        if loc["name"] == lokasjon:
            lat = loc["lat"]
            lon = loc["lon"]
            break
    
    # Lag yr.no lenke med koordinater (alltid riktig)
    metno_url = f"https://www.yr.no/nb/v%C3%A6rvarsel/daglig-tabell/{lat},{lon}"
    
    # Bygg Slack-melding med blocks
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*⚠️ Værvarsel: {lokasjon}*\n\n{melding}"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Se værvarsel på yr.no",
                        "emoji": True
                    },
                    "url": metno_url,
                    "style": "primary"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Met.no Værvarsel"
                }
            ]
        }
    ]
    
    payload = {
        "blocks": blocks
    }
    
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        print(f"✓ Varsel sendt til Slack for {lokasjon}")
    except requests.exceptions.RequestException as e:
        print(f"✗ Feil ved sending til Slack: {e}")


def sjekk_lokasjon(lokasjon: Dict):
    """Sjekker værvarsler for en lokasjon og sender varsler ved behov"""
    navn = lokasjon["name"]
    lat = lokasjon["lat"]
    lon = lokasjon["lon"]
    
    print(f"\n📍 Sjekker {navn}...")
    
    varsler = []
    forecast_info = ""
    
    # Hent værdata
    værdata = hent_værdata(lat, lon)
    if værdata:
        # Sjekk nedbør
        nedbør = analyser_nedbør(værdata)
        timer_dekket = nedbør.get("timer_dekket", 0)
        forecast_info = f"📊 _Varsel dekker neste {timer_dekket} timer_"
        
        if nedbør["max_per_time"] >= THRESHOLDS["nedbør_mm_per_time"]:
            varsler.append(f"🌧️ *Kraftig nedbør:* opptil {nedbør['max_per_time']:.1f} mm/time")
        
        if nedbør["total_24t"] >= THRESHOLDS["nedbør_mm_per_dag"]:
            varsler.append(f"🌧️ *Mye nedbør:* {nedbør['total_24t']:.1f} mm neste 24t")
        
        # Vis også total nedbør over hele perioden hvis betydelig
        if nedbør["total_periode"] > nedbør["total_24t"] * 1.5:  # Mer enn 50% ekstra
            varsler.append(f"🌧️ *Total nedbør ({timer_dekket}t):* {nedbør['total_periode']:.1f} mm")
        
        # Sjekk temperatur
        temp = analyser_temperatur(værdata)
        
        # Bruk den største svingningen (24t eller hele perioden)
        max_sving = max(temp["sving_24t"], temp["sving"])
        if max_sving >= THRESHOLDS["temp_sving_grader"]:
            if temp["sving"] > temp["sving_24t"]:
                # Stor sving over hele perioden
                varsler.append(
                    f"🌡️ *Store temperatursvingninger:* {temp['min']:.1f}°C → {temp['max']:.1f}°C "
                    f"(forskjell: {temp['sving']:.1f}°C over {temp['timer_dekket']}t)"
                )
            else:
                # Stor sving i første 24t
                varsler.append(
                    f"🌡️ *Store temperatursvingninger:* {temp['min_24t']:.1f}°C → {temp['max_24t']:.1f}°C "
                    f"(forskjell: {temp['sving_24t']:.1f}°C neste 24t)"
                )
    
    # Send varsler til Slack hvis det er noen
    if varsler:
        # Legg til forecast info på slutten
        if forecast_info:
            varsler.append(forecast_info)
        
        melding = "\n\n".join(varsler)
        send_slack_varsel(melding, navn, "warning")
    else:
        print(f"  ✓ Ingen varsler for {navn}")


def send_farevarsler_norge():
    """Sender farevarsler for hele Norge (kun én gang)"""
    print(f"\n⚠️ Sjekker farevarsler for Norge...")
    
    farevarsler = hent_farevarsler_norge()
    if not farevarsler or not farevarsler.get("features"):
        print(f"  ✓ Ingen farevarsler")
        return
    
    varsler = []
    
    # Oversett og formater farevarsler
    event_emoji = {
        "gale": "💨",
        "wind": "🌬️", 
        "rain": "🌧️",
        "snow": "❄️",
        "ice": "🧊",
        "icing": "🧊",
        "avalanches": "⚠️",
        "forestfire": "🔥",
        "flood": "🌊",
        "lightning": "⚡"
    }
    
    severity_map = {
        "Extreme": "🔴 Ekstrem",
        "Severe": "🟠 Alvorlig",
        "Moderate": "🟡 Moderat",
        "Minor": "🟢 Mindre"
    }
    
    for varsel in farevarsler["features"]:
        props = varsel.get("properties", {})
        hendelse = props.get("event", "Ukjent hendelse")
        beskrivelse = props.get("description", "")
        alvorlighet = props.get("severity", "")
        omrade = props.get("area", "")
        
        # Få emoji for hendelse
        emoji = event_emoji.get(hendelse.lower(), "⚠️")
        severity_text = severity_map.get(alvorlighet, alvorlighet)
        
        # Oversett hendelser
        hendelse_norsk = {
            "gale": "Sterk vind/kuling",
            "wind": "Vind", 
            "rain": "Kraftig regn",
            "snow": "Kraftig snø",
            "ice": "Is/glatt",
            "icing": "Ising",
            "avalanches": "Snøskredfare",
            "forestfire": "Skogbrannfare",
            "flood": "Flom",
            "lightning": "Lyn"
        }.get(hendelse.lower(), hendelse)
        
        varsel_tekst = f"{emoji} *{hendelse_norsk}* ({severity_text})"
        if omrade:
            varsel_tekst += f"\n   _Område: {omrade}_"
        if beskrivelse:
            varsel_tekst += f"\n   _{beskrivelse}_"
        
        varsler.append(varsel_tekst)
    
    # Send alle farevarsler samlet
    if varsler:
        melding = "\n\n".join(varsler)
        send_slack_varsel(melding, "Norge - Farevarsler", "danger")


def main():
    """Hovedfunksjon"""
    print("=" * 60)
    print("🌤️  Værvarsel Monitor - Met.no API")
    print("=" * 60)
    print(f"Startet: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if SLACK_WEBHOOK_URL == "DIN_SLACK_WEBHOOK_URL_HER":
        print("\n⚠️ ADVARSEL: Husk å sette SLACK_WEBHOOK_URL i scriptet!")
        return
    
    # Send farevarsler for Norge først (kun én gang)
    send_farevarsler_norge()
    time.sleep(1)
    
    # Samle værvarsler per type
    kraftig_nedbor_kommuner = []
    mye_nedbor_kommuner = []
    temp_sving_kommuner = []
    
    # Sjekk alle kommuner
    for lokasjon in LOCATIONS:
        navn = lokasjon["name"]
        lat = lokasjon["lat"]
        lon = lokasjon["lon"]
        
        print(f"\n📍 Sjekker {navn}...")
        
        # Hent værdata
        værdata = hent_værdata(lat, lon)
        if værdata:
            # Sjekk nedbør
            nedbør = analyser_nedbør(værdata)
            
            if nedbør["max_per_time"] >= THRESHOLDS["nedbør_mm_per_time"]:
                kraftig_nedbor_kommuner.append({
                    "navn": navn,
                    "verdi": nedbør["max_per_time"],
                    "lat": lat,
                    "lon": lon
                })
            
            if nedbør["total_24t"] >= THRESHOLDS["nedbør_mm_per_dag"]:
                mye_nedbor_kommuner.append({
                    "navn": navn,
                    "verdi": nedbør["total_24t"],
                    "lat": lat,
                    "lon": lon
                })
            
            # Sjekk temperatur
            temp = analyser_temperatur(værdata)
            max_sving = max(temp["sving_24t"], temp["sving"])
            
            if max_sving >= THRESHOLDS["temp_sving_grader"]:
                temp_sving_kommuner.append({
                    "navn": navn,
                    "min": temp["min"] if temp["sving"] > temp["sving_24t"] else temp["min_24t"],
                    "max": temp["max"] if temp["sving"] > temp["sving_24t"] else temp["max_24t"],
                    "sving": max_sving,
                    "lat": lat,
                    "lon": lon
                })
        
        time.sleep(1)  # Vær høflig mot API-et
    
    # Send grupperte varsler
    if kraftig_nedbor_kommuner:
        send_gruppert_varsel_nedbor_time(kraftig_nedbor_kommuner)
        time.sleep(1)
    
    if mye_nedbor_kommuner:
        send_gruppert_varsel_nedbor_dogn(mye_nedbor_kommuner)
        time.sleep(1)
    
    if temp_sving_kommuner:
        send_gruppert_varsel_temperatur(temp_sving_kommuner)
        time.sleep(1)
    
    if not kraftig_nedbor_kommuner and not mye_nedbor_kommuner and not temp_sving_kommuner:
        print("\n✓ Ingen værvarsler for noen kommuner")
    
    print("\n✓ Ferdig!")
    print("=" * 60)


def send_gruppert_varsel_nedbor_time(kommuner):
    """Sender gruppert varsel for kraftig nedbør per time"""
    print(f"\n🌧️ Sender varsel om kraftig nedbør for {len(kommuner)} kommuner")
    
    # Sorter etter verdi (høyeste først)
    kommuner_sortert = sorted(kommuner, key=lambda x: x["verdi"], reverse=True)
    
    # Bygg melding
    kommune_liste = []
    for k in kommuner_sortert:
        kommune_liste.append(f"• *{k['navn']}:* {k['verdi']:.1f} mm/time")
    
    melding = f"🌧️ *Kraftig nedbør varslet*\n\n" + "\n".join(kommune_liste)
    melding += f"\n\n📊 _Terskelverdi: {THRESHOLDS['nedbør_mm_per_time']:.1f} mm/time_"
    
    # Bruk første kommune som representativ lenke
    send_slack_varsel_gruppert(melding, "Kraftig nedbør", kommuner_sortert[0]["lat"], kommuner_sortert[0]["lon"])


def send_gruppert_varsel_nedbor_dogn(kommuner):
    """Sender gruppert varsel for mye nedbør per døgn"""
    print(f"\n🌧️ Sender varsel om mye nedbør for {len(kommuner)} kommuner")
    
    # Sorter etter verdi (høyeste først)
    kommuner_sortert = sorted(kommuner, key=lambda x: x["verdi"], reverse=True)
    
    # Bygg melding
    kommune_liste = []
    for k in kommuner_sortert:
        kommune_liste.append(f"• *{k['navn']}:* {k['verdi']:.1f} mm/24t")
    
    melding = f"🌧️ *Mye nedbør neste døgn*\n\n" + "\n".join(kommune_liste)
    melding += f"\n\n📊 _Terskelverdi: {THRESHOLDS['nedbør_mm_per_dag']:.1f} mm/24t_"
    
    # Bruk første kommune som representativ lenke
    send_slack_varsel_gruppert(melding, "Mye nedbør", kommuner_sortert[0]["lat"], kommuner_sortert[0]["lon"])


def send_gruppert_varsel_temperatur(kommuner):
    """Sender gruppert varsel for temperatursvingninger"""
    print(f"\n🌡️ Sender varsel om temperatursvingninger for {len(kommuner)} kommuner")
    
    # Sorter etter sving (største først)
    kommuner_sortert = sorted(kommuner, key=lambda x: x["sving"], reverse=True)
    
    # Bygg melding
    kommune_liste = []
    for k in kommuner_sortert:
        kommune_liste.append(f"• *{k['navn']}:* {k['min']:.1f}°C → {k['max']:.1f}°C (Δ {k['sving']:.1f}°C)")
    
    melding = f"🌡️ *Store temperatursvingninger varslet*\n\n" + "\n".join(kommune_liste)
    melding += f"\n\n📊 _Terskelverdi: {THRESHOLDS['temp_sving_grader']:.1f}°C_"
    
    # Bruk første kommune som representativ lenke
    send_slack_varsel_gruppert(melding, "Temperatursvingninger", kommuner_sortert[0]["lat"], kommuner_sortert[0]["lon"])


def send_slack_varsel_gruppert(melding: str, tittel: str, lat: float, lon: float):
    """Sender gruppert varsel til Slack"""
    
    # Lag yr.no lenke med koordinater
    metno_url = f"https://www.yr.no/nb/v%C3%A6rvarsel/daglig-tabell/{lat},{lon}"
    
    # Bygg Slack-melding med blocks
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*⚠️ Værvarsel: {tittel}*\n\n{melding}"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Se værvarsel på yr.no",
                        "emoji": True
                    },
                    "url": metno_url,
                    "style": "primary"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Met.no Værvarsel"
                }
            ]
        }
    ]
    
    payload = {
        "blocks": blocks
    }
    
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        print(f"✓ Gruppert varsel sendt til Slack: {tittel}")
    except requests.exceptions.RequestException as e:
        print(f"✗ Feil ved sending til Slack: {e}")


if __name__ == "__main__":
    main()
