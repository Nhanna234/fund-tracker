import streamlit as st

from core import analytics as an
from core import state
from core.ui import empty_state, inr, page_header, style_table

c = state.ctx()
page_header("Tax (estimate)", "Capital gains on equity delivery, by Indian financial year (Apr–Mar). FIFO lots, net of charges.",
            eyebrow="Insights")

lots = an.tax_lots(c.lots)
if lots.empty:
    empty_state("No realized gains yet — sell something to see tax estimates.")
    st.stop()

summ = an.tax_summary(c.lots)
fys = list(summ["FY"])
fy = st.selectbox("Financial year", fys, index=0)
row = summ[summ["FY"] == fy].iloc[0]

k = st.columns(5)
k[0].metric("Short-term (STCG)", inr(row["STCG"], sign=True), delta=f"taxed @ {row['STCG rate'] * 100:.0f}%", delta_color="off")
k[1].metric("Long-term (LTCG)", inr(row["LTCG"], sign=True), delta=f"exempt up to {inr(row['LTCG exemption'])}",
            delta_color="off")
k[2].metric("Taxable LTCG", inr(row["Taxable LTCG"]), delta=f"taxed @ {row['LTCG rate'] * 100:.1f}%", delta_color="off")
k[3].metric("Estimated tax", inr(row["Est. tax"]))
k[4].metric("Loss to carry forward", inr(row["Carry-fwd loss"]))

st.markdown("**Lots sold in " + fy + "**")
fl = lots[lots["fy"] == row["fy"]][["symbol", "buy_date", "sell_date", "qty", "buy_price", "sell_price", "charges",
                                     "pnl", "days", "term"]]
fl.columns = ["Stock", "Bought", "Sold", "Qty", "Buy", "Sell", "Charges", "Gain ₹", "Days", "Term"]
st.dataframe(style_table(fl.sort_values("Sold"), money=["Gain ₹"], money2=["Buy", "Sell", "Charges"], nums=["Qty", "Days"],
                         dates=["Bought", "Sold"], pnl_cols=["Gain ₹"]), hide_index=True, width="stretch")
st.download_button("Download lots (CSV)", fl.to_csv(index=False), file_name=f"capital_gains_{fy.replace(' ', '_')}.csv",
                   icon=":material/download:")

with st.expander("All years"):
    s = summ.drop(columns=["fy", "STCG rate", "LTCG rate"])
    st.dataframe(style_table(s, money=["STCG", "LTCG", "LTCG exemption", "Taxable LTCG", "Est. tax", "Carry-fwd loss"],
                             pnl_cols=["STCG", "LTCG"]), hide_index=True, width="stretch")

st.caption("⚠️ Estimate only, not tax advice. Rates: FY 2024-25 onwards STCG 20%, LTCG 12.5% above ₹1.25 L "
           "(earlier 15% / 10% above ₹1 L; FY 2024-25 had split rates around 23 Jul 2024 which are not separated here). "
           "Gains are net of all charges incl. STT (STT is not deductible for tax), no grandfathering (pre-2018 holdings), "
           "no surcharge/cess, no carry-forward from previous years. Verify with your broker's tax P&L / a CA.")
