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
LOCATIONS = [
    {"name": "Oslo", "lat": 59.9139, "lon": 10.7522},
    {"name": "Bergen", "lat": 60.3913, "lon": 5.3221},
    {"name": "Trondheim", "lat": 63.4305, "lon": 10.3951},
    {"name": "Grimstad", "lat": 58.3405, "lon": 8.5933},
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


def hent_farevarsler(lat: float, lon: float) -> Optional[Dict]:
    """Henter farevarsler fra Met.no MetAlerts API"""
    url = "https://api.met.no/weatherapi/metalerts/2.0/current.json"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Filtrer varsler som gjelder for lokasjon
        relevante_varsler = []
        sett_varsler = set()  # For å unngå duplikater
        
        if "features" in data:
            for feature in data["features"]:
                props = feature.get("properties", {})
                
                # Sjekk om varslet gjelder for Norge (Norge har county-koder)
                if props.get("county"):
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


def analyser_nedbør(værdata: Dict) -> Dict[str, float]:
    """Analyserer nedbørsmengder fra værdata"""
    timeseries = værdata.get("properties", {}).get("timeseries", [])
    
    max_nedbør_time = 0.0
    total_nedbør_24t = 0.0
    
    now = datetime.utcnow()
    
    for i, entry in enumerate(timeseries[:24]):  # Se på neste 24 timer
        details = entry.get("data", {}).get("next_1_hours", {}).get("details", {})
        nedbør = details.get("precipitation_amount", 0.0)
        
        max_nedbør_time = max(max_nedbør_time, nedbør)
        total_nedbør_24t += nedbør
    
    return {
        "max_per_time": max_nedbør_time,
        "total_24t": total_nedbør_24t
    }


def analyser_temperatur(værdata: Dict) -> Dict[str, float]:
    """Analyserer temperatursvingninger"""
    timeseries = værdata.get("properties", {}).get("timeseries", [])
    
    temperaturer = []
    for entry in timeseries[:24]:  # Neste 24 timer
        instant = entry.get("data", {}).get("instant", {}).get("details", {})
        temp = instant.get("air_temperature")
        if temp is not None:
            temperaturer.append(temp)
    
    if not temperaturer:
        return {"min": 0, "max": 0, "sving": 0}
    
    min_temp = min(temperaturer)
    max_temp = max(temperaturer)
    sving = max_temp - min_temp
    
    return {
        "min": min_temp,
        "max": max_temp,
        "sving": sving
    }


def send_slack_varsel(melding: str, lokasjon: str, alvorlighetsgrad: str = "warning"):
    """Sender varsel til Slack via webhook"""
    
    color_map = {
        "danger": "#ff0000",
        "warning": "#ffaa00", 
        "good": "#00ff00"
    }
    
    payload = {
        "attachments": [{
            "color": color_map.get(alvorlighetsgrad, "#ffaa00"),
            "title": f"⚠️ Værvarsel: {lokasjon}",
            "text": melding,
            "footer": "Met.no Værvarsel",
            "ts": int(time.time())
        }]
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
    har_farevarsler = False
    
    # Hent værdata
    værdata = hent_værdata(lat, lon)
    if værdata:
        # Sjekk nedbør
        nedbør = analyser_nedbør(værdata)
        if nedbør["max_per_time"] >= THRESHOLDS["nedbør_mm_per_time"]:
            varsler.append(f"🌧️ *Kraftig nedbør:* {nedbør['max_per_time']:.1f} mm/time")
        
        if nedbør["total_24t"] >= THRESHOLDS["nedbør_mm_per_dag"]:
            varsler.append(f"🌧️ *Mye nedbør:* {nedbør['total_24t']:.1f} mm neste 24 timer")
        
        # Sjekk temperatur
        temp = analyser_temperatur(værdata)
        if temp["sving"] >= THRESHOLDS["temp_sving_grader"]:
            varsler.append(
                f"🌡️ *Store temperatursvingninger:* {temp['min']:.1f}°C → {temp['max']:.1f}°C "
                f"(forskjell: {temp['sving']:.1f}°C)"
            )
    
    # Hent farevarsler
    farevarsler = hent_farevarsler(lat, lon)
    if farevarsler and farevarsler.get("features"):
        har_farevarsler = True
        
        # Oversett og formater farevarsler
        event_emoji = {
            "gale": "💨",
            "wind": "🌬️", 
            "rain": "🌧️",
            "snow": "❄️",
            "ice": "🧊",
            "icing": "🧊",
            "avalanches": "⚠️",
            "forestFire": "🔥",
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
                "forestFire": "Skogbrannfare",
                "flood": "Flom",
                "lightning": "Lyn"
            }.get(hendelse.lower(), hendelse)
            
            varsel_tekst = f"{emoji} *{hendelse_norsk}* ({severity_text})"
            if beskrivelse:
                varsel_tekst += f"\n   _{beskrivelse}_"
            
            varsler.append(varsel_tekst)
    
    # Send varsler til Slack
    if varsler:
        melding = "\n\n".join(varsler)
        alvorlighetsgrad = "danger" if har_farevarsler else "warning"
        send_slack_varsel(melding, navn, alvorlighetsgrad)
    else:
        print(f"  ✓ Ingen varsler for {navn}")


def main():
    """Hovedfunksjon"""
    print("=" * 60)
    print("🌤️  Værvarsel Monitor - Met.no API")
    print("=" * 60)
    print(f"Startet: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if SLACK_WEBHOOK_URL == "DIN_SLACK_WEBHOOK_URL_HER":
        print("\n⚠️ ADVARSEL: Husk å sette SLACK_WEBHOOK_URL i scriptet!")
        return
    
    for lokasjon in LOCATIONS:
        sjekk_lokasjon(lokasjon)
        time.sleep(1)  # Vær høflig mot API-et
    
    print("\n✓ Ferdig!")
    print("=" * 60)


if __name__ == "__main__":
    main()
