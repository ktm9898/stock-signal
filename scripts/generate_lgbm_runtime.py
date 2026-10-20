import os
import json
import joblib

def build_lgbm_runtime_js():
    bundle_path = 'data/meta_lgbm_model.pkl'
    bundle = joblib.load(bundle_path)
    model = bundle['model']
    feature_cols = bundle['feature_cols']
    dumped = model.dump_model()

    def compress_node(node):
        if 'leaf_value' in node:
            return round(float(node['leaf_value']), 6)
        f_idx = int(node['split_feature'])
        th = round(float(node['threshold']), 6)
        left = compress_node(node['left_child'])
        right = compress_node(node['right_child'])
        return [f_idx, th, left, right]

    compressed_trees = []
    for t in dumped['tree_info']:
        compressed_trees.append(compress_node(t['tree_structure']))

    trees_json = json.dumps(compressed_trees, separators=(',', ':'))
    feature_cols_json = json.dumps(feature_cols, separators=(',', ':'))

    js_content = f"""/**
 * LightGBM Meta-Labeling AI Runtime (In-Browser Execution)
 * Converted directly from data/meta_lgbm_model.pkl (120 Trees, 34 Features)
 * Generates exact AI Prob (0~100) identical to screener.py (LightGBM).
 */

(function(global) {{
  'use strict';

  const FEATURE_COLS = {feature_cols_json};
  const TREES = {trees_json};

  function evalNode(node, x) {{
    if (typeof node === 'number') {{
      return node;
    }}
    const fIdx = node[0];
    const th = node[1];
    return x[fIdx] <= th ? evalNode(node[2], x) : evalNode(node[3], x);
  }}

  function predictProbFromFeatures(featureVector) {{
    let rawSum = 0.0;
    for (let i = 0; i < TREES.length; i++) {{
      rawSum += evalNode(TREES[i], featureVector);
    }}
    const prob = 1.0 / (1.0 + Math.exp(-rawSum));
    return Math.round(prob * 1000) / 10; // 0.0 ~ 100.0 (one decimal place)
  }}

  function calculateHistoricalStats(rows, currIdx) {{
    const curr = rows[currIdx];
    const close = Number(curr.close || 0);

    const close3 = currIdx >= 3 ? Number(rows[currIdx - 3].close || close) : close;
    const close5 = currIdx >= 5 ? Number(rows[currIdx - 5].close || close) : close;
    const close20 = currIdx >= 20 ? Number(rows[currIdx - 20].close || close) : close;

    const ret3d = close3 > 0 ? ((close - close3) / close3) * 100.0 : 0.0;
    const ret5d = close5 > 0 ? ((close - close5) / close5) * 100.0 : 0.0;
    const ret20d = close20 > 0 ? ((close - close20) / close20) * 100.0 : 0.0;

    // 20d volatility (std dev of daily returns * 100)
    let volatility20d = 1.0;
    if (currIdx >= 5) {{
      const returns = [];
      const start = Math.max(1, currIdx - 19);
      for (let j = start; j <= currIdx; j++) {{
        const prevC = Number(rows[j - 1].close || 0);
        const thisC = Number(rows[j].close || 0);
        if (prevC > 0) {{
          returns.push((thisC - prevC) / prevC);
        }}
      }}
      if (returns.length >= 4) {{
        const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
        const variance = returns.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / (returns.length - 1);
        volatility20d = Math.sqrt(Math.max(0, variance)) * 100.0;
      }}
    }}

    const rsi5 = currIdx >= 5 && rows[currIdx - 5].rsi !== undefined ? Number(rows[currIdx - 5].rsi) : Number(curr.rsi || 50);
    const disp5 = currIdx >= 5 && rows[currIdx - 5].disparity20 !== undefined ? Number(rows[currIdx - 5].disparity20) : Number(curr.disparity20 || 100);

    const rsiSlope5d = Number(curr.rsi || 50) - rsi5;
    const dispSlope5d = Number(curr.disparity20 || 100) - disp5;

    return {{ ret3d, ret5d, ret20d, volatility20d, rsiSlope5d, dispSlope5d }};
  }}

  /**
   * Main entry point for computing AI Score for a buy candidate.
   * @param {{Object}} stock - Stock wrapper with rows array
   * @param {{number}} rowIdx - Index of current date row in stock.rows
   * @param {{Array}} indexRows - Array of index rows (KOSPI or KOSDAQ)
   * @param {{number}} concurrentCount - Number of buy signals triggered on this day
   * @returns {{number}} AI Score (0.0 ~ 100.0)
   */
  function computeLGBMAiScore(stock, rowIdx, indexRows, concurrentCount) {{
    if (!stock || !stock.rows || rowIdx < 0 || rowIdx >= stock.rows.length) {{
      return 50.0;
    }}

    const curr = stock.rows[rowIdx];
    const sStats = calculateHistoricalStats(stock.rows, rowIdx);

    // Find matching index row by date
    let iCurr = null;
    let iStats = {{ ret3d: 0.0, ret5d: 0.0, ret20d: 0.0, volatility20d: 1.0 }};
    if (indexRows && indexRows.length > 0) {{
      const currDate = curr.date;
      const iIdx = indexRows.findIndex(r => r.date === currDate);
      if (iIdx >= 0) {{
        iCurr = indexRows[iIdx];
        iStats = calculateHistoricalStats(indexRows, iIdx);
      }}
    }}

    const stockRsi = Number(curr.rsi !== undefined ? curr.rsi : 50.0);
    const stockBbPct = Number(curr.bb_pct !== undefined ? curr.bb_pct : (curr.b_band_pct !== undefined ? curr.b_band_pct : 0.5));
    const stockBbWidth = Number(curr.bb_width !== undefined ? curr.bb_width : 0.1);
    const stockDisp = Number(curr.disparity20 !== undefined ? curr.disparity20 : 100.0);
    const stockVr = Number(curr.volume_ratio !== undefined ? curr.volume_ratio : 100.0);
    const stockAdx = Number(curr.adx !== undefined ? curr.adx : 20.0);
    const stockMinusDi = Number(curr.minus_di !== undefined ? curr.minus_di : 20.0);
    const stockPlusDi = Number(curr.plus_di !== undefined ? curr.plus_di : 20.0);
    const stockMacdOsc = Number(curr.macd_osc !== undefined ? curr.macd_osc : 0.0);
    const stockStochK = Number(curr.stoch_k !== undefined ? curr.stoch_k : 50.0);
    const stockStochD = Number(curr.stoch_d !== undefined ? curr.stoch_d : 50.0);

    const idxRsi = iCurr ? Number(iCurr.rsi !== undefined ? iCurr.rsi : 50.0) : 50.0;
    const idxBbPct = iCurr ? Number(iCurr.bb_pct !== undefined ? iCurr.bb_pct : (iCurr.b_band_pct !== undefined ? iCurr.b_band_pct : 0.5)) : 0.5;
    const idxDisp = iCurr ? Number(iCurr.disparity20 !== undefined ? iCurr.disparity20 : 100.0) : 100.0;
    const idxAdx = iCurr ? Number(iCurr.adx !== undefined ? iCurr.adx : 20.0) : 20.0;
    const idxMinusDi = iCurr ? Number(iCurr.minus_di !== undefined ? iCurr.minus_di : 20.0) : 20.0;
    const idxPlusDi = iCurr ? Number(iCurr.plus_di !== undefined ? iCurr.plus_di : 20.0) : 20.0;
    const idxMacdOsc = iCurr ? Number(iCurr.macd_osc !== undefined ? iCurr.macd_osc : 0.0) : 0.0;

    const fDict = {{
      'stock_rsi': stockRsi,
      'stock_bb_pct': stockBbPct,
      'stock_bb_width': stockBbWidth,
      'stock_disparity20': stockDisp,
      'stock_volume_ratio': stockVr,
      'stock_adx': stockAdx,
      'stock_minus_di': stockMinusDi,
      'stock_plus_di': stockPlusDi,
      'stock_macd_osc': stockMacdOsc,
      'stock_stoch_k': stockStochK,
      'stock_stoch_d': stockStochD,
      'stock_ret_3d': sStats.ret3d,
      'stock_ret_5d': sStats.ret5d,
      'stock_ret_20d': sStats.ret20d,
      'stock_volatility_20d': sStats.volatility20d,
      'stock_rsi_slope_5d': sStats.rsiSlope5d,
      'stock_disp_slope_5d': sStats.dispSlope5d,
      'idx_rsi': idxRsi,
      'idx_bb_pct': idxBbPct,
      'idx_disparity20': idxDisp,
      'idx_adx': idxAdx,
      'idx_minus_di': idxMinusDi,
      'idx_plus_di': idxPlusDi,
      'idx_macd_osc': idxMacdOsc,
      'idx_ret_3d': iStats.ret3d,
      'idx_ret_5d': iStats.ret5d,
      'idx_ret_20d': iStats.ret20d,
      'idx_volatility_20d': iStats.volatility20d,
      'rel_ret_5d': sStats.ret5d - iStats.ret5d,
      'rel_ret_20d': sStats.ret20d - iStats.ret20d,
      'rel_rsi': stockRsi - idxRsi,
      'rel_disparity': stockDisp - idxDisp,
      'concurrent_signals_count': Number(concurrentCount || 1.0),
      'trigger_group': 1.0
    }};

    const featureVector = new Float64Array(FEATURE_COLS.length);
    for (let f = 0; f < FEATURE_COLS.length; f++) {{
      const val = fDict[FEATURE_COLS[f]];
      featureVector[f] = (val !== undefined && !isNaN(val)) ? val : 0.0;
    }}

    return predictProbFromFeatures(featureVector);
  }}

  // Export to global window scope / Node.js
  const metaObj = {{
    computeScore: computeLGBMAiScore,
    predictFromVector: predictProbFromFeatures,
    featureCols: FEATURE_COLS
  }};

  if (typeof window !== 'undefined') {{
    window.LGBMMetaModel = metaObj;
  }}
  if (typeof global !== 'undefined') {{
    global.LGBMMetaModel = metaObj;
  }}
  if (typeof module !== 'undefined' && module.exports) {{
    module.exports = metaObj;
  }}
}})(typeof window !== 'undefined' ? window : (typeof global !== 'undefined' ? global : this));
"""

    out_path = 'data/meta_lgbm_runtime.js'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(js_content)
    print(f"[SUCCESS] Generated {out_path} ({len(js_content) / 1024:.2f} KB)")

if __name__ == "__main__":
    build_lgbm_runtime_js()
