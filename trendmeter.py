# app.py
"""
YouTube Viral Topics Tool — Final (API key inlined)
⚠️ SECURITY REMINDER: The API key is embedded in this file. Do NOT commit this file to a public repository.
"""

import streamlit as st
import requests
from datetime import datetime, timedelta
import re
import csv
import io
import os

st.set_page_config(page_title="YouTube Viral Topics Tool — Final", layout="wide")

# -------------------------
# === INLINE API KEY ===
# -------------------------
API_KEY = "AIzaSyC8nrFFraG69j9B_34t61W9xvK3-Ptl2UM"  # <<-- inlined as requested

# -------------------------
# Helper functions
# -------------------------
def parse_iso8601_duration_to_seconds(duration):
    """
    Parse ISO-8601 duration (e.g. PT1H2M3S, PT45S) to seconds.
    """
    if not duration or not duration.startswith("PT"):
        return 0
    hours = minutes = seconds = 0
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", duration)
    if not m:
        numbers = re.findall(r"(\d+\.?\d*)([HMS])", duration)
        for val, unit in numbers:
            try:
                if unit == "H":
                    hours = float(val)
                elif unit == "M":
                    minutes = float(val)
                elif unit == "S":
                    seconds = float(val)
            except:
                pass
        total = int(hours * 3600 + minutes * 60 + seconds)
        return total
    h, mm, s = m.groups()
    if h:
        hours = int(h)
    if mm:
        minutes = int(mm)
    if s:
        seconds = int(s)
    return hours * 3600 + minutes * 60 + seconds

def parse_rfc3339_to_datetime(ts):
    """
    Parse timestamp like '2020-01-01T12:34:56Z' or with fractional seconds.
    """
    if not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1]
    if "." in ts:
        ts = ts.split(".")[0]
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        try:
            return datetime.strptime(ts, "%Y-%m-%d")
        except:
            return None

def seconds_to_readable(seconds):
    if seconds is None:
        return "N/A"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"

def safe_int(value):
    try:
        return int(value)
    except:
        return 0

# -------------------------
# Endpoints
# -------------------------
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEO_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels"

# -------------------------
# UI Inputs
# -------------------------
st.title("YouTube Viral Topics Tool — Final")
st.write("Paste keywords, set filters, fetch recent videos. Average video duration is included per channel.")

col1, col2 = st.columns([2, 1])

with col1:
    keywords_input = st.text_area(
        "Keywords (one per line or comma-separated)",
        value="""Affair Relationship Stories
Reddit Update
Reddit Relationship Advice
Reddit Cheating
AITA Update
Open Relationship""",
        height=160,
    )

    # Normalize keywords list
    if "," in keywords_input and "\n" not in keywords_input.strip():
        keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
    else:
        keywords = [k.strip() for k in re.split(r"[\n,]+", keywords_input) if k.strip()]

    days = st.number_input("Search last N days", min_value=1, max_value=90, value=7)
    max_results_per_keyword = st.slider("Results per keyword (search API max 50)", 1, 50, 5)

with col2:
    st.header("Filters")
    min_views = st.number_input("Min video views", min_value=0, value=0)
    min_subs = st.number_input("Min channel subscribers (0 = no min)", min_value=0, value=0)
    max_subs = st.number_input("Max channel subscribers (0 = no max)", min_value=0, value=3000)
    min_channel_age_months = st.number_input("Min channel age (months, 0 = no min)", min_value=0, value=0)
    only_shorts = st.checkbox("Only Shorts (avg duration < 60s)", value=False)
    country_code = st.text_input("Country code filter (ISO 2-letter, optional)", value="")

if not API_KEY:
    st.error("API key not found in code. Please add your key to API_KEY variable at top of file.")
    st.stop()

# -------------------------
# Fetch Data
# -------------------------
if st.button("Fetch Data"):
    start_ts = (datetime.utcnow() - timedelta(days=int(days))).isoformat("T") + "Z"

    progress_text = st.empty()
    progress_bar = st.progress(0)
    all_results = []
    channel_duration_map = {}
    channel_video_count_map = {}
    channel_subs_map = {}
    channel_published_map = {}
    processed_channels = set()

    total_keywords = len(keywords)
    if total_keywords == 0:
        st.warning("No keywords provided.")
        st.stop()

    try:
        for idx, keyword in enumerate(keywords, start=1):
            progress_text.write(f"({idx}/{total_keywords}) Searching: {keyword}")
            # search
            search_params = {
                "part": "snippet",
                "q": keyword,
                "type": "video",
                "order": "viewCount",
                "publishedAfter": start_ts,
                "maxResults": max_results_per_keyword,
                "key": API_KEY,
            }
            resp = requests.get(YOUTUBE_SEARCH_URL, params=search_params)
            if resp.status_code != 200:
                st.error(f"Search API failed for '{keyword}' (status {resp.status_code}).")
                continue
            search_data = resp.json()
            videos = search_data.get("items", [])
            if not videos:
                st.info(f"No videos for keyword: {keyword}")
                progress_bar.progress(int((idx/total_keywords)*100))
                continue

            video_ids = []
            channel_ids = []
            vid_to_ch = {}
            for v in videos:
                vid = v.get("id", {}).get("videoId")
                if not vid:
                    continue
                video_ids.append(vid)
                ch = v.get("snippet", {}).get("channelId")
                if ch:
                    channel_ids.append(ch)
                    vid_to_ch[vid] = ch

            if not video_ids:
                progress_bar.progress(int((idx/total_keywords)*100))
                continue

            # videos details
            stats_params = {
                "part": "statistics,contentDetails,snippet",
                "id": ",".join(video_ids),
                "key": API_KEY,
            }
            stats_resp = requests.get(YOUTUBE_VIDEO_URL, params=stats_params)
            if stats_resp.status_code != 200:
                st.error(f"Videos API failed for '{keyword}' (status {stats_resp.status_code}).")
                continue
            stats_items = stats_resp.json().get("items", [])

            # fetch channel details for new channels
            unique_channel_ids = list({cid for cid in channel_ids if cid not in processed_channels})
            if unique_channel_ids:
                channels_params = {
                    "part": "snippet,statistics",
                    "id": ",".join(unique_channel_ids),
                    "key": API_KEY,
                }
                ch_resp = requests.get(YOUTUBE_CHANNEL_URL, params=channels_params)
                if ch_resp.status_code == 200:
                    ch_items = ch_resp.json().get("items", [])
                    for ch in ch_items:
                        cid = ch.get("id")
                        subs = safe_int(ch.get("statistics", {}).get("subscriberCount", 0))
                        pub = ch.get("snippet", {}).get("publishedAt")
                        channel_subs_map[cid] = subs
                        channel_published_map[cid] = pub
                        processed_channels.add(cid)
                else:
                    st.warning(f"Channels API returned {ch_resp.status_code} for some channels.")

            # process videos
            for item in stats_items:
                vid = item.get("id")
                snip = item.get("snippet", {})
                ch_id = snip.get("channelId")
                title = snip.get("title", "N/A")
                description = (snip.get("description") or "")[:300]
                url = f"https://www.youtube.com/watch?v={vid}"
                views = safe_int(item.get("statistics", {}).get("viewCount", 0))
                likes = safe_int(item.get("statistics", {}).get("likeCount", 0))
                comments = safe_int(item.get("statistics", {}).get("commentCount", 0))
                duration_iso = item.get("contentDetails", {}).get("duration", "PT0S")
                duration_seconds = parse_iso8601_duration_to_seconds(duration_iso)
                publish_ts = snip.get("publishedAt")
                publish_dt = parse_rfc3339_to_datetime(publish_ts)

                if ch_id:
                    channel_duration_map.setdefault(ch_id, []).append(duration_seconds)
                    channel_video_count_map[ch_id] = channel_video_count_map.get(ch_id, 0) + 1

                all_results.append({
                    "keyword": keyword,
                    "video_id": vid,
                    "title": title,
                    "description": description,
                    "url": url,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "duration_seconds": duration_seconds,
                    "duration_readable": seconds_to_readable(duration_seconds),
                    "channel_id": ch_id,
                    "channel_subs": channel_subs_map.get(ch_id, None),
                    "video_published_at": publish_dt.isoformat() if publish_dt else None
                })

            progress_bar.progress(int((idx/total_keywords)*100))

        # aggregate per-channel
        channel_info_map = {}
        for ch_id, durations in channel_duration_map.items():
            avg_sec = sum(durations) / len(durations) if durations else 0
            avg_readable = seconds_to_readable(avg_sec)
            subs = channel_subs_map.get(ch_id, None)
            published_at = channel_published_map.get(ch_id)
            ch_age_months = None
            if published_at:
                dt = parse_rfc3339_to_datetime(published_at)
                if dt:
                    now = datetime.utcnow()
                    ch_age_months = (now.year - dt.year) * 12 + (now.month - dt.month)
            channel_info_map[ch_id] = {
                "avg_duration_seconds": avg_sec,
                "avg_duration_readable": avg_readable,
                "subs": subs,
                "published_at": published_at,
                "age_months": ch_age_months,
                "video_count_in_sample": channel_video_count_map.get(ch_id, 0)
            }

        # filter channels
        filtered_channels = {}
        for row in all_results:
            ch_id = row["channel_id"]
            if not ch_id:
                continue
            chinfo = channel_info_map.get(ch_id, {})
            if not chinfo:
                continue

            if row["views"] < min_views:
                continue
            subs = chinfo.get("subs") or row.get("channel_subs") or 0
            if min_subs and subs < min_subs:
                continue
            if max_subs and max_subs > 0 and subs > max_subs:
                continue
            age_m = chinfo.get("age_months")
            if min_channel_age_months and (age_m is None or age_m < min_channel_age_months):
                continue
            avg_sec = chinfo.get("avg_duration_seconds", 0)
            if only_shorts and avg_sec >= 60:
                continue

            filtered_channels.setdefault(ch_id, {
                "channel_id": ch_id,
                "subs": subs,
                "avg_duration_seconds": chinfo.get("avg_duration_seconds"),
                "avg_duration_readable": chinfo.get("avg_duration_readable"),
                "video_count_in_sample": chinfo.get("video_count_in_sample"),
                "sample_videos": []
            })
            filtered_channels[ch_id]["sample_videos"].append({
                "title": row["title"],
                "url": row["url"],
                "views": row["views"],
                "duration": row["duration_readable"],
                "published": row["video_published_at"]
            })

        # display
        st.write("---")
        st.subheader(f"Channels found: {len(filtered_channels)} (matching filters)")

        csv_rows = []
        for cid, info in filtered_channels.items():
            csv_rows.append({
                "channel_id": cid,
                "subs": info["subs"],
                "avg_duration_seconds": int(info["avg_duration_seconds"] or 0),
                "avg_duration_readable": info["avg_duration_readable"],
                "video_count_in_sample": info["video_count_in_sample"],
                "sample_video_1_title": info["sample_videos"][0]["title"] if info["sample_videos"] else "",
                "sample_video_1_url": info["sample_videos"][0]["url"] if info["sample_videos"] else "",
                "sample_video_1_views": info["sample_videos"][0]["views"] if info["sample_videos"] else 0,
            })

        cols = st.columns(2)
        idx = 0
        for cid, info in sorted(filtered_channels.items(), key=lambda x: (x[1]["subs"] or 0)):
            card_col = cols[idx % 2]
            with card_col:
                st.markdown(f"### Channel: `{cid}`")
                st.write(f"**Subscribers:** {info['subs'] or 'N/A'}")
                st.write(f"**Average duration (sample):** {info['avg_duration_readable']} ({int(info['avg_duration_seconds'])}s) over {info['video_count_in_sample']} sample videos")
                st.write("**Sample videos:**")
                for v in info["sample_videos"][:5]:
                    st.markdown(f"- [{v['title']}]({v['url']}) — {v['views']} views — {v['duration']} — published: {v['published']}")
                st.write("---")
            idx += 1

        # CSV download
        if csv_rows:
            df_buffer = io.StringIO()
            writer = csv.DictWriter(df_buffer, fieldnames=csv_rows[0].keys())
            writer.writeheader()
            writer.writerows(csv_rows)
            st.download_button("Download channels CSV", df_buffer.getvalue(), "channels_results.csv", "text/csv")

        if not filtered_channels:
            st.warning("No channels passed the filters. Try widening filters or increase results per keyword.")
    except Exception as e:
        st.error(f"An error occurred: {e}")
    finally:
        progress_bar.empty()
        progress_text.empty()
