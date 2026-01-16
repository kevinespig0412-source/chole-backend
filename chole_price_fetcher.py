"""
Chole Price Fetcher
Fetches commodity prices from Yahoo Finance
Runs daily at 6 AM ET via GitHub Actions
"""

import os
import json
from datetime import datetime
import yfinance as yf
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
def init_firebase():
    if not firebase_admin._apps:
        service_account = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT', '{}'))
        if service_account:
            cred = credentials.Certificate(service_account)
        else:
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    return firestore.client()


# Commodity tickers (Yahoo Finance symbols)
COMMODITIES = [
    {"symbol": "GC=F", "name": "Gold", "display": "Gold", "unit": "/oz"},
    {"symbol": "SI=F", "name": "Silver", "display": "Silver", "unit": "/oz"},
    {"symbol": "HG=F", "name": "Copper", "display": "Copper", "unit": "/lb"},
    {"symbol": "UXA=F", "name": "Uranium", "display": "Uranium", "unit": "/lb"},  # May need alternative source
    {"symbol": "PL=F", "name": "Platinum", "display": "Platinum", "unit": "/oz"},
    {"symbol": "PA=F", "name": "Palladium", "display": "Palladium", "unit": "/oz"},
    {"symbol": "ALI=F", "name": "Aluminum", "display": "Aluminum", "unit": "/lb"},
    {"symbol": "NI=F", "name": "Nickel", "display": "Nickel", "unit": "/lb"},
]

# Additional mining ETFs for reference
ETFS = [
    {"symbol": "GDX", "name": "VanEck Gold Miners ETF", "display": "GDX"},
    {"symbol": "GDXJ", "name": "VanEck Junior Gold Miners ETF", "display": "GDXJ"},
    {"symbol": "SIL", "name": "Global X Silver Miners ETF", "display": "SIL"},
    {"symbol": "COPX", "name": "Global X Copper Miners ETF", "display": "COPX"},
    {"symbol": "URA", "name": "Global X Uranium ETF", "display": "URA"},
    {"symbol": "LIT", "name": "Global X Lithium ETF", "display": "LIT"},
]


def fetch_price(symbol):
    """Fetch current price and change for a symbol"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d")
        
        if len(hist) < 1:
            return None
        
        current_price = hist['Close'].iloc[-1]
        
        # Calculate change
        if len(hist) >= 2:
            prev_price = hist['Close'].iloc[-2]
            change = current_price - prev_price
            change_pct = (change / prev_price) * 100
        else:
            change = 0
            change_pct = 0
        
        return {
            "price": round(current_price, 2),
            "change": round(change, 2),
            "changePct": round(change_pct, 2),
            "up": change_pct >= 0
        }
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None


def format_price(price, unit=""):
    """Format price for display"""
    if price >= 1000:
        return f"${price:,.0f}{unit}"
    elif price >= 100:
        return f"${price:.0f}{unit}"
    elif price >= 10:
        return f"${price:.2f}{unit}"
    else:
        return f"${price:.3f}{unit}"


def format_change(change_pct):
    """Format change percentage"""
    sign = "+" if change_pct >= 0 else ""
    return f"{sign}{change_pct:.1f}%"


def fetch_all_prices():
    """Fetch all commodity prices"""
    prices = []
    
    for commodity in COMMODITIES:
        print(f"Fetching {commodity['name']}...")
        data = fetch_price(commodity['symbol'])
        
        if data:
            prices.append({
                "symbol": commodity['display'],
                "name": commodity['name'],
                "value": format_price(data['price'], commodity['unit']),
                "rawPrice": data['price'],
                "change": format_change(data['changePct']),
                "changePct": data['changePct'],
                "up": data['up']
            })
        else:
            # Placeholder if fetch fails
            prices.append({
                "symbol": commodity['display'],
                "name": commodity['name'],
                "value": "N/A",
                "rawPrice": 0,
                "change": "0.0%",
                "changePct": 0,
                "up": True
            })
    
    return prices


def fetch_etf_prices():
    """Fetch mining ETF prices"""
    etf_prices = []
    
    for etf in ETFS:
        print(f"Fetching {etf['name']}...")
        data = fetch_price(etf['symbol'])
        
        if data:
            etf_prices.append({
                "symbol": etf['display'],
                "name": etf['name'],
                "value": f"${data['price']:.2f}",
                "rawPrice": data['price'],
                "change": format_change(data['changePct']),
                "changePct": data['changePct'],
                "up": data['up']
            })
    
    return etf_prices


def fetch_uranium_spot():
    """
    Fetch uranium spot price from alternative source
    Since Yahoo Finance doesn't have reliable uranium futures
    """
    # Uranium spot price typically requires scraping or API
    # For now, return a placeholder that can be updated manually
    # or integrated with a uranium price API (e.g., Numerco, Cameco)
    return {
        "symbol": "Uranium",
        "name": "Uranium U3O8",
        "value": "$95/lb",
        "rawPrice": 95.0,
        "change": "+0.0%",
        "changePct": 0.0,
        "up": True
    }


def save_to_firestore(db, prices, etf_prices):
    """Save prices to Firestore"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    data = {
        "date": today,
        "updatedAt": firestore.SERVER_TIMESTAMP,
        "commodities": prices,
        "etfs": etf_prices,
        "note": "Previous close prices"
    }
    
    try:
        # Save by date
        db.collection("commodity_prices").document(today).set(data)
        # Save as latest
        db.collection("commodity_prices").document("latest").set(data)
        print(f"Prices saved for {today}")
    except Exception as e:
        print(f"Firestore save error: {e}")


def main():
    """Main execution function"""
    print(f"Starting Chole Price Fetcher at {datetime.now().isoformat()}")
    
    # Initialize
    db = init_firebase()
    
    # Fetch commodity prices
    print("\nFetching commodity prices...")
    prices = fetch_all_prices()
    
    # Fetch ETF prices
    print("\nFetching ETF prices...")
    etf_prices = fetch_etf_prices()
    
    # Print summary
    print("\n--- COMMODITY PRICES ---")
    for p in prices:
        arrow = "▲" if p['up'] else "▼"
        print(f"{p['symbol']}: {p['value']} {arrow} {p['change']}")
    
    print("\n--- ETF PRICES ---")
    for e in etf_prices:
        arrow = "▲" if e['up'] else "▼"
        print(f"{e['symbol']}: {e['value']} {arrow} {e['change']}")
    
    # Save to Firestore
    print("\nSaving to Firestore...")
    save_to_firestore(db, prices, etf_prices)
    
    print(f"\nCompleted at {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
