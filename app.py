#!/usr/bin/env python3
"""
app.py — Streamlit dashboard for the NSE (NIFTY) screener.

Run:  streamlit run app.py        (NOT `python app.py`)

Hardened against the "blank page" failure mode:
  * Title + version render immediately, before anything that can fail.
  * Imports are guarded — a missing package shows a message, not a blank page.
  * Nothing auto-fetches; the UI appears instantly and waits for a button.
  * The whole render is wrapped so any runtime error shows on-page.
"""

import streamlit as st

st.set_page_config(page_title="NSE NIFTY Screener", layout="wide",
                   initial_sidebar_state="expanded")

# ---- First visible output: proves the page is alive ----------------------
st.title("🇮🇳 NSE NIFTY Buy-Zone / Upside Screener")
st.caption(f"App loaded ✓  ·  Streamlit {st.__version__}  ·  Prices in ₹  ·  "
           "Not financial advice.")

# ---- Guarded imports ------------------------------------------------------
_missing = []
try:
    import pandas as pd
except Exception as e:  # noqa: BLE001
    _missing.append(f"pandas ({e})")
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except Exception as e:  # noqa: BLE001
    _missing.append(f"plotly ({e})")
try:
    import config, data, analytics, export
except Exception as e:  # noqa: BLE001
    _missing.append(f"local modules ({e})")

if _missing:
    st.error("Missing/broken dependencies:\n\n- " + "\n- ".join(_missing) +
             "\n\nFix with:  `pip install -r requirements.txt`")
    st.stop()

CUR = config.CURRENCY

# ---- Sidebar diagnostics (helps debug environment issues) ----------------
with st.sidebar.expander("🩺 Diagnostics", expanded=False):
    import sys
    st.write({"python": sys.version.split()[0], "streamlit": st.__version__,
              "pandas": pd.__version__})
    try:
        import yfinance as yf
        st.write({"yfinance": yf.__version__})
    except Exception as e:  # noqa: BLE001
        st.write(f"yfinance import issue: {e}")


def fetch(universe_kind, top_n, with_news, workers, force):
    tickers = data.get_universe(universe_kind, top_n)
    prices = data.get_prices(tickers, refresh=force)
    funds = data.get_fundamentals(tickers, workers=workers,
                                  with_news=with_news, refresh=force)
    feats = analytics.build_features(prices, funds)
    return prices, funds, feats


# ---- Sidebar controls -----------------------------------------------------
st.sidebar.title("⚙️ Controls")
st.sidebar.subheader("Universe")
universe_kind = st.sidebar.selectbox(
    "Source", ["nifty50", "wiki"],
    help="nifty50 = curated NIFTY 50; wiki = live constituents from Wikipedia")
top_n = st.sidebar.slider("How many tickers", 10, 50, 50, step=5)
with_news = st.sidebar.checkbox("Fetch recent news", value=False)
workers = st.sidebar.slider("Download workers", 1, 12, 6)

c1, c2 = st.sidebar.columns(2)
run = c1.button("🔄 Fetch data", use_container_width=True)
force = c2.button("♻️ Force refresh", use_container_width=True)

st.sidebar.subheader("Composite weights")
st.sidebar.caption("Re-ranks instantly. Auto-normalized.")
w_raw = {
    "analyst_upside": st.sidebar.slider("Analyst upside", 0.0, 1.0, config.WEIGHTS["analyst_upside"], 0.05),
    "buy_zone": st.sidebar.slider("Buy zone", 0.0, 1.0, config.WEIGHTS["buy_zone"], 0.05),
    "valuation": st.sidebar.slider("Valuation (vs peers)", 0.0, 1.0, config.WEIGHTS["valuation"], 0.05),
    "quality": st.sidebar.slider("Quality (vs peers)", 0.0, 1.0, config.WEIGHTS["quality"], 0.05),
    "momentum": st.sidebar.slider("Momentum", 0.0, 1.0, config.WEIGHTS["momentum"], 0.05),
}
_tot = sum(w_raw.values()) or 1.0
weights = {k: v / _tot for k, v in w_raw.items()}

with st.sidebar.expander("Buy-zone thresholds (advanced)"):
    bz = dict(config.BUY_ZONE)
    bz["rsi_overbought"] = st.slider("RSI overbought cap", 55, 80, config.BUY_ZONE["rsi_overbought"])
    bz["pos52w_extended"] = st.slider("Max 52w position", 0.70, 1.0, config.BUY_ZONE["pos52w_extended"], 0.01)
    bz["uptrend_sma200_floor"] = st.slider("Uptrend floor (price/SMA200)", 0.80, 1.0,
                                           config.BUY_ZONE["uptrend_sma200_floor"], 0.01)

min_upside = st.sidebar.slider("Min implied upside for 'actionable'", 0.0, 0.5,
                               config.MIN_IMPLIED_UPSIDE, 0.05)

# ---- Fetch ONLY on button press (never auto-runs) ------------------------
if run or force:
    with st.spinner("Downloading 5y prices + fundamentals from Yahoo (30–90s)..."):
        try:
            prices, funds, feats = fetch(universe_kind, top_n, with_news, workers, force)
            st.session_state.update(prices=prices, funds=funds, feats=feats)
            st.success(f"Loaded {len(feats)} names.")
        except Exception as e:  # noqa: BLE001
            st.exception(e)

feats = st.session_state.get("feats")
prices = st.session_state.get("prices", {})
funds = st.session_state.get("funds", {})

if feats is None or len(feats) == 0:
    st.info("👈 Click **Fetch data** in the sidebar to download and rank the "
            "NIFTY universe. (First run takes ~30–90s; data is cached for 12h.)")
    st.stop()

# ---- Everything below runs only once we have data ------------------------
try:
    ranked = analytics.score(feats, weights=weights, bz=bz)
    actionable = ranked[(ranked["buy_zone"]) & (ranked["implied_upside"] >= min_upside)]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Universe", len(ranked))
    m2.metric("In buy zone", int(ranked["buy_zone"].sum()))
    m3.metric(f"Actionable (≥{min_upside:.0%})", len(actionable))
    med = ranked["implied_upside"].median()
    m4.metric("Median implied upside", f"{med:.1%}" if pd.notna(med) else "—")

    tab_rank, tab_explore, tab_detail = st.tabs(["🏆 Rankings", "🔭 Explore", "🔍 Detail"])
    DISPLAY = export.DISPLAY

    # ---- Rankings ----
    with tab_rank:
        only_act = st.checkbox("Show only actionable (buy-zone & min upside)", value=False)
        view = actionable if only_act else ranked
        show = view[[c for c in DISPLAY if c in view.columns]].copy()
        fmt_all = {
            "price": f"{CUR}{{:.2f}}", "target_mean": f"{CUR}{{:.2f}}", "fwd_pe": "{:.1f}",
            "rsi": "{:.0f}", "beta": "{:.2f}", "composite": "{:.1f}",
            "implied_upside": "{:.1%}", "pos_52w": "{:.0%}", "dist_sma200": "{:+.1%}",
            "rev_growth": "{:.1%}", "roe": "{:.1%}", "ann_vol": "{:.0%}",
            "score_analyst": "{:.0f}", "score_buy_zone": "{:.0f}", "score_valuation": "{:.0f}",
            "score_quality": "{:.0f}", "score_momentum": "{:.0f}",
        }
        fmt_map = {k: v for k, v in fmt_all.items() if k in show.columns}
        styled = show.style.format(fmt_map, na_rep="—")
        try:
            styled = styled.background_gradient(subset=["composite"], cmap="Greens")
        except Exception:  # noqa: BLE001
            pass
        st.dataframe(styled, use_container_width=True, height=620)

        dl1, dl2 = st.columns(2)
        dl1.download_button("⬇️ CSV", ranked.to_csv().encode(), "nse_screen.csv",
                            "text/csv", use_container_width=True)
        try:
            dl2.download_button(
                "⬇️ Excel (.xlsx)", export.to_excel_bytes(ranked), "nse_screen.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True)
        except Exception as e:  # noqa: BLE001
            dl2.caption(f"Excel export needs openpyxl ({e})")

    # ---- Explore ----
    with tab_explore:
        plot_df = ranked.reset_index()
        plot_df["mc"] = plot_df["marketCap"].fillna(plot_df["marketCap"].median()).clip(lower=1) ** 0.5
        mc_max = plot_df["mc"].max() or 1.0
        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown("**Implied upside vs Composite**")
            fig = go.Figure()
            for sec, g in plot_df.groupby("sector"):
                fig.add_trace(go.Scatter(
                    x=g["composite"], y=g["implied_upside"] * 100, mode="markers+text",
                    text=[t.replace(config.SUFFIX, "") for t in g["ticker"]],
                    textposition="top center", name=str(sec),
                    marker=dict(size=g["mc"] / mc_max * 26 + 6), hovertext=g["name"]))
            fig.add_hline(y=min_upside * 100, line_dash="dot", line_color="grey")
            fig.update_layout(height=460, xaxis_title="Composite", yaxis_title="Implied upside %",
                              legend=dict(font=dict(size=9)), margin=dict(t=10))
            st.plotly_chart(fig, use_container_width=True)
        with cc2:
            st.markdown("**Valuation vs Quality (sector-relative)**")
            fig2 = go.Figure()
            for sec, g in plot_df.groupby("sector"):
                fig2.add_trace(go.Scatter(
                    x=g["score_valuation"], y=g["score_quality"], mode="markers+text",
                    text=[t.replace(config.SUFFIX, "") for t in g["ticker"]],
                    textposition="top center", name=str(sec), marker=dict(size=12)))
            fig2.update_layout(height=460, xaxis_title="Valuation (cheap→)",
                               yaxis_title="Quality", legend=dict(font=dict(size=9)), margin=dict(t=10))
            st.plotly_chart(fig2, use_container_width=True)
        st.markdown("**Sector averages**")
        st.dataframe(ranked.groupby("sector")[
            ["composite", "implied_upside", "score_valuation", "score_quality"]
        ].mean().round(2).sort_values("composite", ascending=False), use_container_width=True)

    # ---- Detail ----
    with tab_detail:
        labels = {t: f"{t.replace(config.SUFFIX, '')} — {ranked.loc[t, 'name']}" for t in ranked.index}
        pick = st.selectbox("Ticker", ranked.index.tolist(), format_func=lambda t: labels.get(t, t))
        row = ranked.loc[pick]
        st.subheader(f"{pick.replace(config.SUFFIX, '')} — {row['name']}  ·  {row['sector']}")
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Price", f"{CUR}{row['price']:.2f}")
        d2.metric("Composite", f"{row['composite']:.1f}")
        d3.metric("Implied upside", f"{row['implied_upside']:.1%}" if pd.notna(row["implied_upside"]) else "—")
        d4.metric("RSI", f"{row['rsi']:.0f}" if pd.notna(row["rsi"]) else "—")
        d5.metric("Buy zone", "✅" if row["buy_zone"] else "—")

        if pick in prices:
            df = prices[pick].copy()
            close = df["Close"]
            sma50 = close.rolling(config.SMA_FAST).mean()
            sma200 = close.rolling(config.SMA_SLOW).mean()
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                row_heights=[0.72, 0.28], vertical_spacing=0.03)
            fig.add_trace(go.Scatter(x=df.index, y=close, name="Close", line=dict(width=1.4)), 1, 1)
            fig.add_trace(go.Scatter(x=df.index, y=sma50, name="SMA50", line=dict(width=1, dash="dot")), 1, 1)
            fig.add_trace(go.Scatter(x=df.index, y=sma200, name="SMA200", line=dict(width=1, dash="dash")), 1, 1)
            if pd.notna(row.get("target_mean")):
                fig.add_hline(y=row["target_mean"], line_dash="dot", line_color="green",
                              annotation_text="mean target", row=1, col=1)
            delta = close.diff()
            gain = delta.clip(lower=0).ewm(alpha=1 / config.RSI_PERIOD, adjust=False).mean()
            loss = (-delta.clip(upper=0)).ewm(alpha=1 / config.RSI_PERIOD, adjust=False).mean()
            rsi_series = 100 - 100 / (1 + gain / loss.replace(0, float("nan")))
            fig.add_trace(go.Scatter(x=df.index, y=rsi_series, name="RSI", line=dict(width=1)), 2, 1)
            fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color="blue", row=2, col=1)
            fig.update_layout(height=520, margin=dict(t=10), legend=dict(orientation="h"))
            st.plotly_chart(fig, use_container_width=True)

        dl, dr = st.columns(2)
        with dl:
            st.markdown("**Sub-score breakdown**")
            subs = row[["score_analyst", "score_buy_zone", "score_valuation",
                        "score_quality", "score_momentum"]]
            bar = go.Figure(go.Bar(x=subs.values, y=[s.replace("score_", "") for s in subs.index],
                                   orientation="h", marker_color="#2e7d32"))
            bar.update_layout(height=260, xaxis_range=[0, 100], margin=dict(t=10, l=10))
            st.plotly_chart(bar, use_container_width=True)
        with dr:
            st.markdown("**Analyst target range**")
            if pd.notna(row.get("target_low")) and pd.notna(row.get("target_high")):
                st.write(f"Low **{CUR}{row['target_low']:.0f}** · Mean **{CUR}{row['target_mean']:.0f}** · "
                         f"High **{CUR}{row['target_high']:.0f}**")
                st.write(f"Analysts: {row.get('n_analysts')} · Rec mean: {row.get('rec_mean')}")
            else:
                st.write("No analyst targets available (common for NSE names on Yahoo).")
            if row.get("is_financial"):
                st.caption("⚠︎ Financial (bank / NBFC / insurer): revenue & P/S "
                           "metrics are unreliable here — P/S omitted, growth "
                           "recomputed from annual statements where available.")
            st.markdown("**Key fundamentals**")
            rg = (f"{row['rev_growth']:.1%}" if pd.notna(row.get("rev_growth")) else "—")
            src = row.get("rev_growth_source")
            raw = row.get("rev_growth_raw")
            if src and src != "annual_stmt" and pd.notna(raw):
                rg += f"  (Yahoo snapshot raw: {raw*100:.0f}% · {src})"
            elif src == "annual_stmt":
                rg += "  (from annual statements)"
            st.write({
                "Fwd P/E": round(row["fwd_pe"], 1) if pd.notna(row["fwd_pe"]) else None,
                "Rev growth": rg,
                "ROE": f"{row['roe']:.1%}" if pd.notna(row["roe"]) else None,
                "Beta": round(row["beta"], 2) if pd.notna(row["beta"]) else None,
                "Ann. vol": f"{row['ann_vol']:.0%}" if pd.notna(row["ann_vol"]) else None,
            })

        news = funds.get(pick, {}).get("news", [])
        if news:
            st.markdown("**Recent headlines**")
            for it in news[:5]:
                t, link = it.get("title"), it.get("link")
                st.markdown(f"- [{t}]({link})" if link else f"- {t}")

except Exception as e:  # noqa: BLE001
    st.error("Something failed while rendering. Traceback below — paste it to me:")
    st.exception(e)
