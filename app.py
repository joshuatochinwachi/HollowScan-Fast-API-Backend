#!/usr/bin/env python3
"""
app.py
Professional FastAPI backend for HollowScan Mobile App.
Provides endpoints for feed, categories, and subscription management.
"""

from fastapi import FastAPI, HTTPException, Depends, Query, Header
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
import os
import json
import hashlib
import string
import random
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from supabase_utils import get_supabase_config, sanitize_text

app = FastAPI(title="HollowScan Mobile API", version="1.0.0")

# Enable CORS for mobile development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------
# CONFIGURATION
# -------------------
URL, KEY = get_supabase_config()
HEADERS = {
    'apikey': KEY,
    'Authorization': f'Bearer {KEY}',
    'Content-Type': 'application/json'
}

# Mirrors telegram_bot.py initial_channels
DEFAULT_CHANNELS = [
    {"id": "1367813504786108526", "name": "Collectors Amazon", "url": "https://discord.com/channels/653646362453213205/1367813504786108526", "category": "UK Stores", "enabled": True},
    {"id": "855164313006505994", "name": "Argos Instore", "url": "https://discord.com/channels/653646362453213205/855164313006505994", "category": "UK Stores", "enabled": True},
    {"id": "864504557903937587", "name": "Restocks Online", "url": "https://discord.com/channels/653646362453213205/864504557903937587", "category": "UK Stores", "enabled": True}
]

# -------------------
# IMAGE OPTIMIZATION (mirrors telegram_bot.py)
# -------------------
def optimize_image_url(url: str) -> str:
    """
    Optimize image URLs to force maximum resolution.
    Removes size restrictions from Amazon, eBay, and Discord proxy URLs.
    """
    if not url:
        return url
    
    try:
        # 1. Decode Discord Proxy URLs
        if "images-ext-" in url and "discordapp.net" in url:
            if "/https/" in url:
                url = "https://" + url.split("/https/", 1)[1]
            elif "/http/" in url:
                url = "http://" + url.split("/http/", 1)[1]
        
        # 2. Amazon Image Optimization - Remove size limits
        if any(domain in url for domain in ['media-amazon.com', 'images-amazon.com', 'ssl-images-amazon.com']):
            url = re.sub(r'\._[A-Z_]+[0-9]+_\.', '.', url)
            if "?" in url:
                url = url.split("?")[0]
        
        # 3. eBay Image Optimization - Force max resolution
        if "ebayimg.com" in url:
            if re.search(r's-l\d+\.', url):
                url = re.sub(r's-l\d+\.', 's-l1600.', url)
            if "?" in url:
                url = url.split("?")[0]
        
        # 4. Remove Discord proxy size limits
        if "discordapp.net" in url and "?" in url:
            base = url.split("?")[0]
            url = base
            
    except Exception:
        pass
    
    return url

# -------------------
# DATABASE HELPERS (Using Supabase Schema)
# -------------------
def get_user_by_id(user_id: str) -> Optional[Dict]:
    """Get user from UUID in users table"""
    try:
        response = requests.get(
            f"{URL}/rest/v1/users?id=eq.{user_id}",
            headers=HEADERS,
            timeout=10
        )
        if response.status_code == 200 and response.json():
            return response.json()[0]
    except Exception as e:
        print(f"[DB] Error fetching user: {e}")
    return None

def get_user_by_email(email: str) -> Optional[Dict]:
    """Get user from email in users table"""
    try:
        response = requests.get(
            f"{URL}/rest/v1/users?email=eq.{email}",
            headers=HEADERS,
            timeout=10
        )
        if response.status_code == 200 and response.json():
            return response.json()[0]
    except Exception as e:
        print(f"[DB] Error fetching user by email: {e}")
    return None

def create_user(email: str = None, apple_id: str = None) -> Optional[Dict]:
    """Create new user in users table"""
    try:
        payload = {
            "email": email,
            "apple_id": apple_id,
            "subscription_status": "free",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        response = requests.post(
            f"{URL}/rest/v1/users",
            headers=HEADERS,
            json=payload,
            timeout=10
        )
        if response.status_code in [200, 201]:
            return response.json()[0] if isinstance(response.json(), list) else response.json()
    except Exception as e:
        print(f"[DB] Error creating user: {e}")
    return None

def update_user(user_id: str, updates: Dict) -> bool:
    """Update user in users table"""
    try:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        response = requests.patch(
            f"{URL}/rest/v1/users?id=eq.{user_id}",
            headers=HEADERS,
            json=updates,
            timeout=10
        )
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"[DB] Error updating user: {e}")
    return False

def link_telegram_account(user_id: str, telegram_id: str, telegram_username: str = None) -> Optional[Dict]:
    """Link Telegram account to user via user_telegram_links table"""
    try:
        payload = {
            "user_id": user_id,
            "telegram_id": telegram_id,
            "telegram_username": telegram_username,
            "linked_at": datetime.now(timezone.utc).isoformat()
        }
        response = requests.post(
            f"{URL}/rest/v1/user_telegram_links",
            headers=HEADERS,
            json=payload,
            timeout=10
        )
        if response.status_code in [200, 201]:
            return response.json()[0] if isinstance(response.json(), list) else response.json()
    except Exception as e:
        print(f"[DB] Error linking Telegram: {e}")
    return None

def get_telegram_links_for_user(user_id: str) -> List[Dict]:
    """Get all Telegram links for a user"""
    try:
        response = requests.get(
            f"{URL}/rest/v1/user_telegram_links?user_id=eq.{user_id}",
            headers=HEADERS,
            timeout=10
        )
        if response.status_code == 200:
            return response.json() or []
    except Exception as e:
        print(f"[DB] Error fetching Telegram links: {e}")
    return []

def save_deal(user_id: str, alert_id: str, alert_data: Dict) -> Optional[Dict]:
    """Save deal to saved_deals table"""
    try:
        payload = {
            "user_id": user_id,
            "alert_id": alert_id,
            "alert_data": alert_data,
            "saved_at": datetime.now(timezone.utc).isoformat()
        }
        response = requests.post(
            f"{URL}/rest/v1/saved_deals",
            headers=HEADERS,
            json=payload,
            timeout=10
        )
        if response.status_code in [200, 201]:
            return response.json()[0] if isinstance(response.json(), list) else response.json()
    except Exception as e:
        print(f"[DB] Error saving deal: {e}")
    return None

def get_saved_deals(user_id: str) -> List[Dict]:
    """Get all saved deals for a user"""
    try:
        response = requests.get(
            f"{URL}/rest/v1/saved_deals?user_id=eq.{user_id}",
            headers=HEADERS,
            timeout=10
        )
        if response.status_code == 200:
            return response.json() or []
    except Exception as e:
        print(f"[DB] Error fetching saved deals: {e}")
    return []

def update_user_quota(user_id: str, new_count: int):
    """Update daily free alerts viewed for user"""
    update_user(user_id, {
        "daily_free_alerts_viewed": new_count,
        "last_free_alert_reset": datetime.now(timezone.utc).isoformat()
    })

# Keep old function name for backward compatibility
def get_user_from_db(user_id: str):
    return get_user_by_id(user_id)

# -------------------
# ENDPOINTS
# -------------------

@app.get("/")
async def root():
    return {"status": "online", "app": "HollowScan API", "v": "1.0.0"}

@app.get("/v1/categories")
async def get_categories():
    """
    Fetch categories organized by region.
    Returns structure: { "UK Stores": [...store names...], "USA Stores": [...], "Canada Stores": [...] }
    """
    result = {}
    channels = []
    
    # Try remote channels.json
    try:
        channels_response = requests.get(
            f"{URL}/storage/v1/object/public/monitor-data/discord_josh/channels.json",
            timeout=10
        )
        if channels_response.status_code == 200:
            channels = channels_response.json() or []
    except Exception as e:
        print(f"[CATEGORIES] Remote channels fetch failed: {e}")
    
    # Try local channels.json
    if not channels and os.path.exists("data/channels.json"):
        try:
            with open("data/channels.json", "r") as f:
                channels = json.load(f)
        except Exception as e:
            print(f"[CATEGORIES] Local channels read failed: {e}")
    
    # If still no channels, use defaults
    if not channels:
        channels = DEFAULT_CHANNELS
    
    # Initialize regions
    result = {
        "UK Stores": [],
        "USA Stores": [],
        "Canada Stores": []
    }
    
    # Parse channels into categories by full region name
    for channel in channels:
        if not channel.get('enabled', True):
            continue
        
        region_name = channel.get('category', 'USA Stores').strip()
        store_name = channel.get('name', 'Unknown')
        
        # Normalize region names
        if 'UK' in region_name.upper():
            region_name = 'UK Stores'
        elif 'CANADA' in region_name.upper() or region_name.upper().startswith('CA'):
            region_name = 'Canada Stores'
        else:
            region_name = 'USA Stores'
        
        # Add unique store names (subcategories)
        if store_name not in result[region_name]:
            result[region_name].append(store_name)
    
    # Sort subcategories alphabetically and add "ALL" at the beginning
    for region in result:
        result[region] = sorted(result[region])
        result[region].insert(0, "ALL")  # Add ALL option at top
    
    print(f"[CATEGORIES] Loaded categories: {result}")
    return result

# Debug endpoint to check channel-to-region mapping
@app.get("/v1/debug/channels")
async def debug_channels():
    """Debug endpoint: Show which region each channel is mapped to"""
    channels = []
    
    try:
        channels_response = requests.get(
            f"{URL}/storage/v1/object/public/monitor-data/discord_josh/channels.json",
            timeout=10
        )
        if channels_response.status_code == 200:
            channels = channels_response.json() or []
    except: pass

    if not channels and os.path.exists("data/channels.json"):
        try:
            with open("data/channels.json", "r") as f:
                channels = json.load(f)
        except: pass

    if not channels:
        channels = DEFAULT_CHANNELS

    # Build mapping
    mapping = {"UK Stores": [], "USA Stores": [], "Canada Stores": []}
    unknown = []
    known_ids = set()
    
    for c in channels:
        if not c.get('enabled', True):
            continue
            
        ch_id = c.get('id')
        ch_name = c.get('name')
        raw_region = c.get('category', 'USA Stores').strip()
        known_ids.add(ch_id)
        
        # Normalize region
        if raw_region == 'UK Stores' or 'UK' in raw_region.upper():
            msg_region = 'UK Stores'
        elif raw_region == 'Canada Stores' or 'CANADA' in raw_region.upper():
            msg_region = 'Canada Stores'
        elif raw_region == 'USA Stores' or 'USA' in raw_region.upper():
            msg_region = 'USA Stores'
        else:
            msg_region = 'UNKNOWN'
            unknown.append({'id': ch_id, 'name': ch_name, 'raw_category': raw_region})
        
        if msg_region in mapping:
            mapping[msg_region].append({'id': ch_id, 'name': ch_name, 'raw_category': raw_region})
    
    # Find orphaned channel IDs (in messages but not in channels.json)
    try:
        messages_response = requests.get(
            f"{URL}/rest/v1/discord_messages?select=channel_id&order=scraped_at.desc&limit=300",
            headers=HEADERS,
            timeout=15
        )
        if messages_response.status_code == 200:
            messages = messages_response.json()
            orphaned_ids = {}
            for msg in messages:
                ch_id = str(msg.get('channel_id', ''))
                if ch_id and ch_id not in known_ids:
                    orphaned_ids[ch_id] = orphaned_ids.get(ch_id, 0) + 1
            
            # Show top orphaned IDs
            orphaned_list = sorted(orphaned_ids.items(), key=lambda x: x[1], reverse=True)[:10]
            orphaned_detail = [{"id": ch_id, "message_count": count} for ch_id, count in orphaned_list]
        else:
            orphaned_detail = []
    except Exception as e:
        print(f"[DEBUG] Error fetching orphaned IDs: {e}")
        orphaned_detail = []
    
    return {
        "total_channels": len(known_ids),
        "mapping": mapping,
        "unknown_regions": unknown,
        "orphaned_channel_ids": orphaned_detail
    }

# -------------------
# DEDUPLICATION HELPER (mirrors telegram_bot.py)
# -------------------
def _get_content_signature(msg: Dict) -> str:
    """Generate a signature for content-based deduplication (Retailer + Title + Price)"""
    try:
        raw = msg.get("raw_data", {})
        embed = raw.get("embed") or {}
        content = msg.get("content", "")
        
        retailer = ""
        title = ""
        price = ""
        
        # 1. Try Embed extraction
        if embed.get("author"):
            retailer = embed["author"].get("name", "")
        
        title = embed.get("title", "")
        
        # Extract price from embed fields
        for field in embed.get("fields", []):
            name = (field.get("name") or "").lower()
            if "price" in name:
                price = field.get("value", "")
                break
        
        # 2. FALLBACK: Parse plain text content if embed data missing
        if not retailer or not title or not price:
            # Pattern: "@Mention | Product Name | Retailer | Just restocked for £XX.XX"
            if content and "|" in content:
                parts = [p.strip() for p in content.split("|")]
                if len(parts) >= 3:
                    if not title and len(parts) > 1:
                        title = parts[1]
                    if not retailer and len(parts) > 2:
                        retailer = parts[2]
                    if not price:
                        price_match = re.search(r'[£$€]\s*[\d,]+\.?\d*', content)
                        if price_match:
                            price = price_match.group(0)
            
        # Final fallback for Argos or other specific keywords
        if not retailer and "Argos" in content:
            retailer = "Argos Instore"
        
        # Create raw signature and hash it
        raw_sig = f"{retailer}|{title}|{price}".lower().strip()
        
        # If everything is still empty, use content hash or ID
        if raw_sig == "||":
            return hashlib.md5(content.encode()).hexdigest() if content else str(msg.get("id"))
            
        return hashlib.md5(raw_sig.encode()).hexdigest()
    except Exception as e:
        return str(msg.get("id"))

@app.get("/v1/feed")
async def get_feed(
    user_id: str,
    region: Optional[str] = None,
    category: Optional[str] = None,
    offset: int = 0,
    limit: int = 20
):
    """
    Paginated feed of products from discord_messages.
    
    Parameters:
    - region: "UK Stores", "USA Stores", or "Canada Stores"
    - category: Store name (e.g., "Argos Instore", "ALL" for all stores in region)
    """
    import re
    
    # 1. Fetch more messages than needed (oversample for filtering)
    fetch_limit = max(limit * 5, 100)
    query = f"order=scraped_at.desc&offset={offset}&limit={fetch_limit}"
    
    response = requests.get(
        f"{URL}/rest/v1/discord_messages?{query}",
        headers=HEADERS,
        timeout=15
    )

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch messages")
        
    messages = response.json()
    
    # 2. Fetch channel mapping
    channels = []
    
    try:
        channels_response = requests.get(
            f"{URL}/storage/v1/object/public/monitor-data/discord_josh/channels.json",
            timeout=10
        )
        if channels_response.status_code == 200:
            channels = channels_response.json() or []
    except: pass

    if not channels and os.path.exists("data/channels.json"):
        try:
            with open("data/channels.json", "r") as f:
                channels = json.load(f)
        except: pass

    if not channels:
        channels = DEFAULT_CHANNELS

    # Build channel map - prefer channels from JSON over defaults
    channel_map = {}
    
    # First add channels from loaded JSON (takes priority)
    for c in channels:
        if c.get('enabled', True):  # Only include enabled channels
            channel_map[c['id']] = {
                'category': c.get('category', 'USA Stores').strip(),
                'name': c.get('name', 'Unknown').strip()
            }
    
    # Then add DEFAULT_CHANNELS only if not already in map
    for c in DEFAULT_CHANNELS:
        if c['id'] not in channel_map:
            channel_map[c['id']] = {
                'category': c.get('category', 'USA Stores').strip(),
                'name': c.get('name', 'Unknown').strip()
            }
    
    # 3. Transform messages into structured product cards
    def extract_product(msg):
        raw = msg.get("raw_data", {})
        embed = raw.get("embed") or {}
        
        # Get channel info
        ch_id = str(msg.get("channel_id", ""))
        ch_info = channel_map.get(ch_id)
        
        # SKIP messages from unknown channels (not in channels.json)
        if not ch_info:
            print(f"[FEED] Skipping message {msg.get('id')} - channel {ch_id} not in map")
            return None
        
        # Get full region name - use directly from channel category (already normalized)
        raw_region = ch_info.get('category', 'USA Stores').strip()
        
        # Normalize region: ensure it's one of the exact 3 names
        if raw_region == 'UK Stores' or 'UK' in raw_region.upper():
            msg_region = 'UK Stores'
        elif raw_region == 'Canada Stores' or 'CANADA' in raw_region.upper():
            msg_region = 'Canada Stores'
        elif raw_region == 'USA Stores' or 'USA' in raw_region.upper() or 'UNITED STATES' in raw_region.upper():
            msg_region = 'USA Stores'
        else:
            # Default fallback - log this
            print(f"[WARN] Unknown region in channel {ch_id}: '{raw_region}'")
            msg_region = 'USA Stores'
        
        # Subcategory is the store name
        subcategory = ch_info.get('name', 'Unknown')
        
        # Title
        title = embed.get("title") or msg.get("content", "")[:50] or "HollowScan Product"
        
        # Image - OPTIMIZE for high resolution
        image = None
        if embed.get("images"):
            image = optimize_image_url(embed["images"][0])
        elif embed.get("thumbnail"):
            image = optimize_image_url(embed["thumbnail"])
        
        # Prices & ROI from fields
        price, resell, roi = None, None, None
        
        if embed.get("fields"):
            for field in embed["fields"]:
                name = (field.get("name") or "").lower()
                val = field.get("value") or ""
                
                match = re.search(r'[\d,.]+', val)
                num = match.group(0).replace(',', '') if match else None
                
                if num:
                    if "price" in name or "retail" in name or "cost" in name:
                        price = num
                    elif "resell" in name or "resale" in name or "sell" in name:
                        resell = num
                    elif "roi" in name or "profit" in name:
                        roi = num
        
        # FALLBACK: Try to extract price from message content
        if not price:
            content = msg.get("content") or ""
            price_match = re.search(r'[\$£€]\s*([\d,.]+)', content)
            if price_match:
                price = price_match.group(1).replace(',', '')
        
        # Extract links
        all_links = embed.get("links") or []
        categorized_links = {"buy": [], "ebay": [], "fba": [], "other": []}
        primary_buy_url = None
        
        ebay_keywords = ['sold', 'active', 'google', 'ebay']
        fba_keywords = ['keepa', 'amazon', 'selleramp', 'fba', 'camel']
        buy_keywords = ['buy', 'shop', 'purchase', 'checkout', 'cart', 'atc']
        
        for link in all_links:
            url = link.get('url', '')
            text = (link.get('text') or 'Link').strip()
            if not url:
                continue
                
            text_lower = text.lower()
            url_lower = url.lower()
            link_obj = {"text": text, "url": url}
            
            if any(kw in text_lower or kw in url_lower for kw in buy_keywords):
                categorized_links["buy"].append(link_obj)
                if not primary_buy_url:
                    primary_buy_url = url
            elif any(kw in text_lower or kw in url_lower for kw in ebay_keywords):
                categorized_links["ebay"].append(link_obj)
            elif any(kw in text_lower or kw in url_lower for kw in fba_keywords):
                categorized_links["fba"].append(link_obj)
            else:
                categorized_links["other"].append(link_obj)
        
        # Fallback primary URL
        if not primary_buy_url and all_links:
            primary_buy_url = all_links[0].get('url')
        
        return {
            "id": str(msg.get("id")),
            "region": msg_region,
            "store_name": subcategory,
            "product_data": {
                "title": title[:100],
                "image": image or "https://via.placeholder.com/400",
                "price": price,
                "resell": resell,
                "roi": roi,
                "buy_url": primary_buy_url,
                "links": categorized_links
            },
            "created_at": msg.get("scraped_at"),
            "is_locked": False
        }
    
    # 4. Process and filter with DEDUPLICATION
    products = []
    seen_signatures = set()
    
    for msg in messages:
        try:
            sig = _get_content_signature(msg)
            if sig in seen_signatures:
                continue
            
            product = extract_product(msg)
            
            # SKIP if product is None (unknown channel)
            if not product:
                continue
            
            # Skip products without a price
            if not product["product_data"]["price"]:
                continue
            
            # Apply region filter (if specified)
            if region and region.strip() and region != "ALL":
                # Normalize both sides for comparison
                requested_region = region.strip()
                product_region = product["region"].strip()
                
                if product_region != requested_region:
                    continue
            
            # Apply store filter (if specified and not ALL)
            if category and category.strip() and category != "ALL":
                if product["store_name"].upper().strip() != category.upper().strip():
                    continue
            
            products.append(product)
            seen_signatures.add(sig)
            
        except Exception as e:
            print(f"[FEED] Error processing message {msg.get('id')}: {e}")
            continue
    
    # Log what was returned
    region_name = region or "ALL"
    category_name = category or "ALL"
    print(f"[FEED] Returned {len(products)} products for region='{region_name}' category='{category_name}'")
    
    # 5. Check user quota for free users
    user = get_user_from_db(user_id)
    is_premium = user.get("subscription_status") == "active" if user else False
    
    if not is_premium:
        views_used = user.get("daily_free_alerts_viewed", 0) if user else 0
        for i, product in enumerate(products):
            if views_used + i >= 4:
                product["is_locked"] = True
                product["product_data"] = {"locked_message": "Subscribe to unlock"}
    
    return products

@app.get("/v1/alerts/{alert_id}")
async def get_alert_detail(alert_id: str, user_id: str):
    """Detailed product view with quota enforcement."""
    user = get_user_from_db(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    is_premium = user.get("subscription_status") == "active"
    current_views = user.get("daily_free_alerts_viewed", 0)
    
    # 1. Quota Check
    if not is_premium and current_views >= 4:
        raise HTTPException(status_code=403, detail="Daily free limit reached. Subscribe for unlimited access.")
        
    # 2. Fetch Alert
    response = requests.get(
        f"{URL}/rest/v1/alerts?id=eq.{alert_id}",
        headers=HEADERS,
        timeout=10
    )
    
    if response.status_code != 200 or not response.json():
        raise HTTPException(status_code=404, detail="Alert not found")
        
    alert = response.json()[0]
    
    # 3. Increment Counter if viewing for the first time today (simple logic for now)
    if not is_premium:
        update_user_quota(user_id, current_views + 1)
        
    return alert

@app.get("/v1/user/status")
async def get_user_status(user_id: str):
    """Check subscription status and daily quota."""
    user = get_user_from_db(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {
        "status": user.get("subscription_status"),
        "views_used": user.get("daily_free_alerts_viewed", 0),
        "views_limit": 4,
        "is_premium": user.get("subscription_status") == "active"
    }

def generate_link_key() -> str:
    """Generate a random 6-character alphanumeric link key"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(6))

def load_pending_links() -> Dict:
    """Load pending Telegram links from file"""
    links_file = "data/pending_telegram_links.json"
    if os.path.exists(links_file):
        try:
            with open(links_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[TELEGRAM] Error loading pending links: {e}")
    return {}

def save_pending_links(links: Dict) -> bool:
    """Save pending Telegram links to file"""
    links_file = "data/pending_telegram_links.json"
    try:
        os.makedirs(os.path.dirname(links_file), exist_ok=True)
        with open(links_file, 'w') as f:
            json.dump(links, f, indent=2)
        return True
    except Exception as e:
        print(f"[TELEGRAM] Error saving pending links: {e}")
        return False

@app.post("/v1/user/telegram/generate-key")
async def generate_telegram_link_key(user_id: str = Query(...)):
    """
    Generate a link key for Telegram account linking.
    User sends this key to the bot with /link command.
    
    Args:
        user_id: UUID of app user
    
    Returns:
        Link key and instructions
    """
    try:
        print(f"[TELEGRAM] Generating link key for user {user_id}")
        
        # 1. Verify user exists
        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # 2. Generate unique key
        link_key = generate_link_key()
        
        # 3. Store in pending links with expiry (15 minutes)
        pending_links = load_pending_links()
        pending_links[link_key] = {
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            "used": False
        }
        
        if not save_pending_links(pending_links):
            raise HTTPException(status_code=500, detail="Failed to save link key")
        
        print(f"[TELEGRAM] Generated key {link_key} for user {user_id}")
        
        return {
            "success": True,
            "link_key": link_key,
            "message": f"Send this message to @Hollowscan_bot: /link {link_key}",
            "expires_in_minutes": 15
        }
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"[TELEGRAM] Error generating link key: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating link key: {str(e)}")

@app.get("/v1/user/telegram/link-status")
async def check_telegram_link_status(user_id: str = Query(...)):
    """
    Check if user's pending Telegram link has been completed.
    
    Args:
        user_id: UUID of app user
    
    Returns:
        Link status and user info if linked
    """
    try:
        pending_links = load_pending_links()
        
        # Check if any pending link matches this user
        for link_key, link_info in pending_links.items():
            if link_info['user_id'] == user_id and link_info.get('used'):
                # Link was completed
                print(f"[TELEGRAM] Link confirmed for user {user_id}")
                
                # Get the linked telegram chat id from database
                telegram_links = get_telegram_links_for_user(user_id)
                if telegram_links:
                    latest_link = telegram_links[-1]  # Most recent link
                    return {
                        "success": True,
                        "linked": True,
                        "telegram_id": latest_link.get('telegram_id'),
                        "telegram_username": latest_link.get('telegram_username'),
                        "is_premium": latest_link.get('is_premium', False)
                    }
        
        # Not yet linked
        return {
            "success": True,
            "linked": False,
            "message": "Waiting for you to send the link command to the Telegram bot"
        }
            
    except Exception as e:
        print(f"[TELEGRAM] Error checking link status: {e}")
        raise HTTPException(status_code=500, detail=f"Error checking link status: {str(e)}")

@app.post("/v1/user/telegram/link")
async def link_telegram_account_endpoint(user_id: str = Query(...), telegram_chat_id: int = Query(...), telegram_username: str = Query(None)):
    """
    Link a Telegram account to user profile using user_telegram_links table.
    Checks if user has active premium on Telegram bot and syncs status.
    
    Args:
        user_id: UUID of app user
        telegram_chat_id: Telegram chat ID (from bot /start command)
        telegram_username: Optional Telegram username
    
    Returns:
        Updated user subscription status and link info
    """
    try:
        print(f"[TELEGRAM] Linking user {user_id} to chat_id {telegram_chat_id}")
        
        # 1. Verify user exists
        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # 2. Load telegram bot users from data file to check premium status
        telegram_users_path = "data/bot_users.json"
        is_telegram_premium = False
        telegram_expiry = None
        
        if os.path.exists(telegram_users_path):
            with open(telegram_users_path, 'r') as f:
                telegram_users = json.load(f)
                chat_id_str = str(telegram_chat_id)
                telegram_user_data = telegram_users.get(chat_id_str, {})
                
                # Check if premium (expiry in future)
                if telegram_user_data and 'expiry' in telegram_user_data:
                    try:
                        expiry_date = datetime.fromisoformat(telegram_user_data['expiry'].replace('Z', '+00:00'))
                        if expiry_date > datetime.now(timezone.utc):
                            is_telegram_premium = True
                            telegram_expiry = telegram_user_data['expiry']
                            print(f"[TELEGRAM] User is PREMIUM until {telegram_expiry}")
                    except Exception as e:
                        print(f"[TELEGRAM] Error parsing expiry: {e}")
        
        # 3. Store Telegram link in user_telegram_links table
        link_result = link_telegram_account(
            user_id=user_id,
            telegram_id=str(telegram_chat_id),
            telegram_username=telegram_username
        )
        
        if not link_result:
            raise HTTPException(status_code=500, detail="Failed to save Telegram link")
        
        # 4. If premium on Telegram, update subscription in users table
        if is_telegram_premium:
            update_user(user_id, {
                "subscription_status": "active",
                "subscription_end": telegram_expiry,
                "subscription_source": "telegram"
            })
            print(f"[TELEGRAM] User {user_id} upgraded to premium")
        
        # 5. Return response
        return {
            "success": True,
            "message": "Telegram account linked" + (" and premium status synced!" if is_telegram_premium else ""),
            "is_premium": is_telegram_premium,
            "premium_until": telegram_expiry,
            "telegram_chat_id": telegram_chat_id,
            "telegram_username": telegram_username
        }
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"[TELEGRAM] Error linking account: {e}")
        raise HTTPException(status_code=500, detail=f"Error linking Telegram account: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
