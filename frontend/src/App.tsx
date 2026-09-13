import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Activity, ArrowUpRight, CalendarDays, Database, LoaderCircle, RefreshCw, NotebookPen } from 'lucide-react'
import './App.css'

interface BybitExecution {
  external_id: string
  order_id: string | null
  symbol: string
  side: 'Buy' | 'Sell'
  quantity: string
  price: string
  realized_pnl: string
  fee: string
  fee_currency: string | null
  executed_at: string
  is_maker: boolean
}

interface TradeSummary {
  order_id: string
  symbol: string
  side: 'Buy' | 'Sell' | 'Mixed'
  fill_count: number
  quantity: string
  average_price: string
  notional: string
  fees: string
  realized_pnl: string
  executed_at: string
  entry_price?: string | null
  stop_loss?: string | null
  take_profit?: string | null
}

interface AccountMetrics {
  fill_count: number
  trade_count: number
  closed_trades: number
  winners: number
  losers: number
  win_rate: number
  gross_pnl: string
  fees: string
  net_pnl: string
  notional: string
}

interface ChartCandle {
  timestamp: string
  open: string
  high: string
  low: string
  close: string
  volume: string
  turnover: string
}

interface OrderBlock {
  type: 'Bullish OB' | 'Bearish OB'
  start_index: number
  end_index: number
  top: number
  bottom: number
  start_timestamp?: number | string
}

interface FVG {
  type: 'Bullish FVG' | 'Bearish FVG'
  start_index: number
  end_index: number
  top: number
  bottom: number
  label: string
}

interface BOS {
  type: string
  from_index: number
  break_index: number
  price: number
  label: string
}

interface CHoCH {
  type: string
  from_index: number
  break_index: number
  price: number
  label: string
}

interface LiquidityPool {
  type: string
  index: number
  price: number
  label: string
}

interface ParallelChannel {
  slope: number
  intercept: number
  upper_offset: number
  lower_offset: number
  mid_offset: number
  start_upper: number
  end_upper: number
  start_lower: number
  end_lower: number
  start_mid: number
  end_mid: number
  direction: string
}

interface SMCData {
  order_blocks?: OrderBlock[]
  fvgs?: FVG[]
  bos?: BOS[]
  choch?: CHoCH[]
  liquidity_pools?: LiquidityPool[]
  channel?: ParallelChannel
  trade_timing_analysis?: string
}

interface ChartContext {
  available: boolean
  symbol?: string
  interval?: string
  candles: ChartCandle[]
  reason?: string
  smc?: SMCData
}

interface TradeLifecycle {
  direction: string
  entry_price: string
  exit_price: string
  entry_at: string
  exit_at: string
}

interface TradeReview {
  order_id: string
  symbol: string
  rule_status: 'fully compliant' | 'partially compliant' | 'vi1olated' | 'no rule applied'
  compliance_score: number
  matched_rules: string[]
  notes: string
  evidence: string[]
  missing_evidence: string[]
  confidence: number
}

interface AIAnalysis {
  summary: string
  trade_reviews: TradeReview[]
  chart_review: string
  technical_review: string
  fee_impact: string
  long_vs_short: string
  repeated_patterns: string[]
  risk_suggestions: string[]
  discipline_suggestions: string[]
}

interface AnalysisPayload {
  analysis?: AIAnalysis
  detail?: string
  retrieved_knowledge?: KnowledgeRecord[]
  chart_context?: ChartContext
  trade_lifecycle?: TradeLifecycle | null
}

interface KnowledgeRecord {
  id?: string
  title: string
  content: string
  tags: string[]
  category: string
  created_at?: string
  relevance_score?: number
}

interface KnowledgeFormState {
  title: string
  content: string
  tags: string
  category: string
}

const FILL_FEE_PREAMBLE = /^The history contains \d+ fills? across \d+ grouped orders? and \d+ closed P&L events?\. Net realized P&L after fees is [-\d.]+ USDT\.\s*/i

const stripFillFeePreamble = (summary: string) => summary.replace(FILL_FEE_PREAMBLE, '').trim()

const reviewParagraphs = (text: string) => text.split(/(?<=\.)\s+(?=[A-Z])/).map((part) => part.trim()).filter(Boolean)

const apiUrl = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

const initialKnowledge: KnowledgeFormState = { title: '', content: '', tags: '', category: 'trading_rule' }

const formatAlignedPrice = (value?: string | null, ...refs: (string | null | undefined)[]) => {
  const amount = Number(value)
  if (!amount) return '—'
  const places = refs.flatMap((ref) => {
    if (!ref || !Number(ref)) return []
    const text = String(ref)
    const dot = text.indexOf('.')
    return dot === -1 ? [] : [text.length - dot - 1]
  })
  const source = String(value)
  const sourceDot = source.indexOf('.')
  const sourcePlaces = sourceDot === -1 ? 0 : source.length - sourceDot - 1
  if (sourcePlaces > 0 && sourcePlaces <= 6) places.push(sourcePlaces)
  const digits = places.length ? Math.max(...places) : amount >= 100 ? 2 : amount >= 1 ? 4 : 6
  return amount.toFixed(digits)
}

const normalizeAnalysis = (value: Partial<AIAnalysis>): AIAnalysis => ({
  summary: stripFillFeePreamble(value.summary ?? 'Analysis generated from the available trading history.') || 'Analysis generated from the available trading history.',
  trade_reviews: Array.isArray(value.trade_reviews) ? value.trade_reviews.map((review) => ({
    ...review,
    evidence: Array.isArray(review.evidence) ? review.evidence : [],
    missing_evidence: Array.isArray(review.missing_evidence) ? review.missing_evidence : [],
    confidence: typeof review.confidence === 'number' ? review.confidence : 0,
  })) : [],
  chart_review: value.chart_review ?? 'Chart evidence was not provided.',
  technical_review: value.technical_review ?? 'Technical analysis was not provided.',
  fee_impact: value.fee_impact ?? 'No fee-impact summary was returned.',
  long_vs_short: value.long_vs_short ?? 'No directional comparison was returned.',
  repeated_patterns: Array.isArray(value.repeated_patterns) ? value.repeated_patterns : [],
  risk_suggestions: Array.isArray(value.risk_suggestions) ? value.risk_suggestions : [],
  discipline_suggestions: Array.isArray(value.discipline_suggestions) ? value.discipline_suggestions : [],
})

const buildFallbackTradeReviews = (tradeSummaries: TradeSummary[], rules: KnowledgeRecord[]): TradeReview[] => {
  const ruleNames = rules.map((rule) => rule.title).filter(Boolean)
  return tradeSummaries.slice(0, 10).map((trade) => {
    const notional = Number(trade.notional) || 0
    const fees = Number(trade.fees) || 0
    const feeRatio = notional ? (fees / notional) * 100 : 0
    const matchedRules = ruleNames.slice(0, 3)
    let complianceScore = matchedRules.length ? 100 : 0

    if (matchedRules.length && feeRatio > 8) {
      complianceScore -= 30
    }

    const ruleStatus: TradeReview['rule_status'] = !matchedRules.length
      ? 'no rule applied'
      : complianceScore >= 80
        ? 'fully compliant'
        : complianceScore >= 50
          ? 'partially compliant'
          : 'violated'

    return {
      order_id: trade.order_id,
      symbol: trade.symbol,
      rule_status: ruleStatus,
      compliance_score: Math.max(0, Math.min(100, complianceScore)),
      matched_rules: matchedRules,
      notes: ruleStatus === 'fully compliant'
        ? 'Available fill and fee data are consistent with the rulebook. Stop placement cannot be verified from fills, and realized P&L is not a compliance criterion.'
        : ruleStatus === 'partially compliant'
          ? 'Observable process signals such as fee burden are inconsistent with the rulebook. Realized P&L was not used to judge compliance.'
          : ruleStatus === 'violated'
            ? 'Observable process signals are materially inconsistent with the rulebook. Realized P&L was not used to judge compliance.'
            : 'No saved rule was available to assess this trade.',
      evidence: [
        `Recorded realized P&L: ${trade.realized_pnl} USDT.`,
        `Recorded ${trade.fill_count} fill${trade.fill_count === 1 ? '' : 's'} for this order.`,
        `Fees were ${trade.fees} USDT.`,
      ],
      missing_evidence: ['Planned entry and setup conditions.', 'Bybit stop-loss on the related orders.'],
      confidence: 0.45,
    }
  })
}

function parseTimestamp(val: string | number | undefined | null): number {
  if (!val) return 0
  if (typeof val === 'number') {
    return val < 10000000000 ? val * 1000 : val
  }
  const str = String(val).trim()
  if (/^\d+$/.test(str)) {
    const num = Number(str)
    return num < 10000000000 ? num * 1000 : num
  }
  const date = new Date(str)
  const ms = date.getTime()
  return isNaN(ms) ? 0 : ms
}

function computeFallbackSMC(candles: ChartCandle[], entryIdx: number = candles.length): SMCData {
  const n = candles.length
  if (n < 5) return {}

  const values = candles.map((c) => ({
    open: Number(c.open),
    high: Number(c.high),
    low: Number(c.low),
    close: Number(c.close),
    timestamp: parseTimestamp(c.timestamp),
  }))

  const x = values.map((_, i) => i)
  const y = values.map((c) => c.close)
  const meanX = x.reduce((a, b) => a + b, 0) / n
  const meanY = y.reduce((a, b) => a + b, 0) / n
  const num = x.reduce((sum, xi, i) => sum + (xi - meanX) * (y[i] - meanY), 0)
  const den = x.reduce((sum, xi) => sum + (xi - meanX) ** 2, 0) || 1
  const slope = num / den
  const intercept = meanY - slope * meanX

  const upperDev = Math.max(...values.map((c, i) => c.high - (slope * i + intercept)))
  const lowerDev = Math.min(...values.map((c, i) => c.low - (slope * i + intercept)))
  const midOffset = (upperDev + lowerDev) / 2

  const channel: ParallelChannel = {
    slope,
    intercept,
    upper_offset: upperDev,
    lower_offset: lowerDev,
    mid_offset: midOffset,
    start_upper: intercept + upperDev,
    end_upper: slope * (n - 1) + intercept + upperDev,
    start_lower: intercept + lowerDev,
    end_lower: slope * (n - 1) + intercept + lowerDev,
    start_mid: intercept + midOffset,
    end_mid: slope * (n - 1) + intercept + midOffset,
    direction: slope > 0.0001 * meanY ? 'ascending' : slope < -0.0001 * meanY ? 'descending' : 'horizontal',
  }

  const limitIdx = Math.min(Math.max(2, entryIdx), n - 1)
  const obs: OrderBlock[] = []
  const atr = values.reduce((sum, c, i) => sum + (i ? Math.max(c.high - c.low, Math.abs(c.high - values[i - 1].close), Math.abs(c.low - values[i - 1].close)) : c.high - c.low), 0) / n

  for (const mult of [0.25, 0.15]) {
    for (let i = 1; i < limitIdx; i++) {
      const c = values[i]
      const futLimit = Math.min(i + 5, limitIdx + 1)
      if (futLimit <= i + 1) continue

      if (c.close < c.open) {
        const futMax = Math.max(...values.slice(i + 1, futLimit).map((v) => v.high))
        if (futMax - c.high >= atr * mult) {
          let endIdx = limitIdx
          for (let k = i + 1; k <= limitIdx; k++) {
            if (values[k].low < c.low) {
              endIdx = k
              break
            }
          }
          obs.push({
            type: 'Bullish OB',
            start_index: i,
            end_index: endIdx,
            top: Math.max(c.open, c.close),
            bottom: c.low,
          })
        }
      } else if (c.close > c.open) {
        const futMin = Math.min(...values.slice(i + 1, futLimit).map((v) => v.low))
        if (c.low - futMin >= atr * mult) {
          let endIdx = limitIdx
          for (let k = i + 1; k <= limitIdx; k++) {
            if (values[k].high > c.high) {
              endIdx = k
              break
            }
          }
          obs.push({
            type: 'Bearish OB',
            start_index: i,
            end_index: endIdx,
            top: c.high,
            bottom: Math.min(c.open, c.close),
          })
        }
      }
    }
    if (obs.length > 0) break
  }

  const fvgs: FVG[] = []
  for (let i = 1; i < limitIdx; i++) {
    if (i + 1 > limitIdx) break
    if (values[i + 1].low > values[i - 1].high && values[i + 1].low - values[i - 1].high >= atr * 0.10) {
      fvgs.push({
        type: 'Bullish FVG',
        start_index: i - 1,
        end_index: Math.min(i + 12, limitIdx),
        top: values[i + 1].low,
        bottom: values[i - 1].high,
        label: 'FVG',
      })
    } else if (values[i - 1].low > values[i + 1].high && values[i - 1].low - values[i + 1].high >= atr * 0.10) {
      fvgs.push({
        type: 'Bearish FVG',
        start_index: i - 1,
        end_index: Math.min(i + 12, limitIdx),
        top: values[i - 1].low,
        bottom: values[i + 1].high,
        label: 'FVG',
      })
    }
  }

  const swingHighs: Array<{ index: number; price: number }> = []
  const swingLows: Array<{ index: number; price: number }> = []
  for (let i = 2; i < limitIdx; i++) {
    if (i + 2 <= limitIdx && values[i].high > values[i - 1].high && values[i].high > values[i - 2].high && values[i].high > values[i + 1].high && values[i].high > values[i + 2].high) {
      swingHighs.push({ index: i, price: values[i].high })
    }
    if (i + 2 <= limitIdx && values[i].low < values[i - 1].low && values[i].low < values[i - 2].low && values[i].low < values[i + 1].low && values[i].low < values[i + 2].low) {
      swingLows.push({ index: i, price: values[i].low })
    }
  }

  const bos: BOS[] = []
  swingHighs.slice(-3).forEach((sh) => {
    const brk = values.findIndex((v, idx) => idx > sh.index && idx <= limitIdx && v.close > sh.price)
    if (brk > 0) bos.push({ type: 'Bullish BOS', from_index: sh.index, break_index: brk, price: sh.price, label: 'BOS' })
  })
  swingLows.slice(-3).forEach((sl) => {
    const brk = values.findIndex((v, idx) => idx > sl.index && idx <= limitIdx && v.close < sl.price)
    if (brk > 0) bos.push({ type: 'Bearish BOS', from_index: sl.index, break_index: brk, price: sl.price, label: 'BOS' })
  })

  const choch: CHoCH[] = []
  if (swingHighs.length && swingLows.length) {
    const sh = swingHighs[swingHighs.length - 1]
    const sl = swingLows[swingLows.length - 1]
    if (sh.index > sl.index) {
      choch.push({ type: 'Bullish CHoCH', from_index: sl.index, break_index: Math.min(sh.index + 2, limitIdx), price: sl.price, label: 'CHoCH' })
    } else {
      choch.push({ type: 'Bearish CHoCH', from_index: sh.index, break_index: Math.min(sl.index + 2, limitIdx), price: sh.price, label: 'CHoCH' })
    }
  }

  const preHighs = swingHighs.filter((sh) => sh.index <= limitIdx)
  const preLows = swingLows.filter((sl) => sl.index <= limitIdx)
  const liquidity_pools: LiquidityPool[] = []
  if (preHighs.length) {
    const maxHigh = Math.max(...preHighs.map((sh) => sh.price))
    const maxItem = preHighs.find((sh) => sh.price === maxHigh)
    if (maxItem) liquidity_pools.push({ type: 'Buy-side Liquidity', index: maxItem.index, price: maxItem.price, label: 'BSL' })
  }
  if (preLows.length) {
    const minLow = Math.min(...preLows.map((sl) => sl.price))
    const minItem = preLows.find((sl) => sl.price === minLow)
    if (minItem) liquidity_pools.push({ type: 'Sell-side Liquidity', index: minItem.index, price: minItem.price, label: 'SSL' })
  }

  const bullishObs = obs.filter((ob) => ob.type === 'Bullish OB').slice(-2)
  const bearishObs = obs.filter((ob) => ob.type === 'Bearish OB').slice(-2)

  return {
    order_blocks: [...bullishObs, ...bearishObs],
    fvgs: fvgs.slice(-2),
    bos: bos.slice(-2),
    choch: choch.slice(-1),
    liquidity_pools,
    channel,
  }
}

function TradeChart({ context, lifecycle, trade }: { context: ChartContext | null; lifecycle: TradeLifecycle | null; trade: TradeSummary | null }) {
  const [visibleCount, setVisibleCount] = useState(60)
  const [windowStart, setWindowStart] = useState<number | null>(null)
  const [showSMC, setShowSMC] = useState(true)
  const [showChannel, setShowChannel] = useState(true)
  const [showEMAs, setShowEMAs] = useState(true)

  const [slInput, setSlInput] = useState('')
  const [tpInput, setTpInput] = useState('')

  useEffect(() => {
    setWindowStart(null)
  }, [lifecycle?.entry_at, lifecycle?.exit_at, trade?.order_id, context?.symbol])

  if (!context?.candles?.length) return null

  const candles = [...context.candles].sort((left, right) => parseTimestamp(left.timestamp) - parseTimestamp(right.timestamp))

  const findCandleIndex = (ts: string | number | undefined | null) => {
    const targetMs = parseTimestamp(ts)
    if (!targetMs || !candles.length) return -1
    return candles.reduce((bestIdx, candle, idx) => {
      const curMs = parseTimestamp(candle.timestamp)
      const bestMs = parseTimestamp(candles[bestIdx].timestamp)
      return Math.abs(curMs - targetMs) < Math.abs(bestMs - targetMs) ? idx : bestIdx
    }, 0)
  }

  let rawEntryIdx = findCandleIndex(lifecycle?.entry_at)
  let rawExitIdx = findCandleIndex(lifecycle?.exit_at ?? trade?.executed_at)

  if (rawExitIdx < 0) {
    rawExitIdx = candles.length - 10
  }
  if (rawEntryIdx < 0 || rawEntryIdx === rawExitIdx) {
    rawEntryIdx = Math.max(0, rawExitIdx - 15)
  }

  let focusIdx = candles.length - 15
  if (rawEntryIdx >= 0 && rawExitIdx >= 0) {
    focusIdx = Math.floor((rawEntryIdx + rawExitIdx) / 2)
  } else if (rawEntryIdx >= 0) {
    focusIdx = rawEntryIdx
  } else if (rawExitIdx >= 0) {
    focusIdx = rawExitIdx
  }

  const count = Math.min(candles.length, Math.max(20, visibleCount))
  const maxStart = Math.max(0, candles.length - count)
  const tradeRight = Math.max(rawEntryIdx, rawExitIdx)
  const centeredStart = Math.max(0, Math.min(maxStart, focusIdx - Math.floor(count / 2)))
  let startIdx = windowStart == null ? centeredStart : Math.max(0, Math.min(maxStart, windowStart))
  if (tradeRight >= 0 && startIdx + count < tradeRight + 2) {
    startIdx = Math.max(0, Math.min(maxStart, tradeRight + 2 - count))
  }
  const endIdx = Math.min(candles.length, startIdx + count)

  const visible = candles.slice(startIdx, endIdx)
  const panStep = Math.max(4, Math.floor(visible.length / 6))

  const width = 960
  const height = 400
  const padding = { top: 36, right: 110, bottom: 32, left: 60 }

  const entryPrice = Number(lifecycle?.entry_price || trade?.average_price || 0)
  const exitPrice = Number(lifecycle?.exit_price || (entryPrice && trade?.realized_pnl ? Number(trade.average_price) : 0))
  const slPrice = Number(slInput) || 0
  const tpPrice = Number(tpInput) || 0

  const candleHighs = visible.map((candle) => Number(candle.high))
  const candleLows = visible.map((candle) => Number(candle.low))

  const allPrices = [
    ...candleHighs,
    ...candleLows,
    ...(entryPrice > 0 ? [entryPrice] : []),
    ...(exitPrice > 0 ? [exitPrice] : []),
    ...(slPrice > 0 ? [slPrice] : []),
    ...(tpPrice > 0 ? [tpPrice] : []),
  ]

  const maximum = Math.max(...allPrices) * 1.002
  const minimum = Math.min(...allPrices) * 0.998
  const range = maximum - minimum || 1

  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom

  const x = (index: number) => padding.left + ((index + 0.5) / Math.max(1, visible.length)) * chartWidth
  const y = (price: number) => padding.top + ((maximum - price) / range) * chartHeight

  const ema = (period: number) => {
    const alpha = 2 / (period + 1)
    let current = Number(candles[0].close)
    return candles.map((candle) => {
      current = alpha * Number(candle.close) + (1 - alpha) * current
      return current
    }).slice(startIdx, endIdx)
  }

  const ema20 = ema(20)
  const ema50 = ema(50)
  const ema30 = ema(30)

  const entryIndex = rawEntryIdx >= 0 ? rawEntryIdx - startIdx : -1
  const exitIndex = rawExitIdx >= 0 ? rawExitIdx - startIdx : -1

  const fallbackEntryIdx = rawEntryIdx >= 0 ? rawEntryIdx : Math.max(0, candles.length - 15)
  const fallbackSMC = computeFallbackSMC(candles, fallbackEntryIdx)
  const inView = (visStart: number, visEnd: number) => visEnd >= 0 && visStart < visible.length

  // Keep SMC geometry in full-series index space, then map into the zoomed window.
  const backendOBs = context.smc?.order_blocks
    ?.filter((ob) => ob.start_index < rawEntryIdx)
    ?.map((ob) => ({
      ...ob,
      visStart: ob.start_index - startIdx,
      visEnd: Math.min(ob.end_index, rawEntryIdx) - startIdx,
    }))
    ?.filter((ob) => inView(ob.visStart, ob.visEnd))

  const rawOBs = (backendOBs && backendOBs.length > 0)
    ? backendOBs
    : (fallbackSMC.order_blocks || []).map((ob) => ({
        ...ob,
        visStart: ob.start_index - startIdx,
        visEnd: Math.min(ob.end_index, fallbackEntryIdx) - startIdx,
      })).filter((ob) => inView(ob.visStart, ob.visEnd))

  // Deduplicate overlapping OBs to keep the chart clean and legible
  const finalOBs: typeof rawOBs = []
  for (let i = rawOBs.length - 1; i >= 0; i--) {
    const ob = rawOBs[i]
    const clashing = finalOBs.some(
      (existing) => existing.type === ob.type && (
        Math.abs(existing.visStart - ob.visStart) <= 2 ||
        (ob.bottom <= existing.top && ob.top >= existing.bottom)
      )
    )
    if (!clashing) finalOBs.unshift(ob)
    if (finalOBs.length >= 2) break
  }

  const backendFVGs = context.smc?.fvgs
    ?.filter((fvg) => fvg.start_index < rawEntryIdx)
    ?.map((fvg) => ({
      ...fvg,
      visStart: fvg.start_index - startIdx,
      visEnd: Math.min(fvg.end_index, rawEntryIdx) - startIdx,
    }))
    ?.filter((fvg) => fvg.visEnd >= 0 && fvg.visStart < visible.length)

  const rawFVGs = (backendFVGs && backendFVGs.length > 0)
    ? backendFVGs
    : (fallbackSMC.fvgs || []).map((fvg) => ({
        ...fvg,
        visStart: fvg.start_index - startIdx,
        visEnd: Math.min(fvg.end_index, fallbackEntryIdx) - startIdx,
      })).filter((fvg) => inView(fvg.visStart, fvg.visEnd))

  // Deduplicate overlapping FVGs
  const finalFVGs: typeof rawFVGs = []
  for (let i = rawFVGs.length - 1; i >= 0; i--) {
    const fvg = rawFVGs[i]
    const clashing = finalFVGs.some(
      (existing) => Math.abs(existing.visStart - fvg.visStart) <= 2 ||
        (fvg.bottom <= existing.top && fvg.top >= existing.bottom)
    )
    if (!clashing) finalFVGs.unshift(fvg)
    if (finalFVGs.length >= 2) break
  }

  const backendBOS = context.smc?.bos
    ?.filter((b) => b.break_index <= rawEntryIdx)
    ?.map((b) => ({
      ...b,
      visFrom: b.from_index - startIdx,
      visBreak: b.break_index - startIdx,
    }))
    ?.filter((b) => b.visBreak >= 0 && b.visFrom < visible.length)

  const rawBOS = (backendBOS && backendBOS.length > 0)
    ? backendBOS
    : (fallbackSMC.bos || []).map((b) => ({
        ...b,
        visFrom: b.from_index - startIdx,
        visBreak: Math.min(b.break_index, fallbackEntryIdx) - startIdx,
      })).filter((b) => b.visBreak >= 0 && b.visFrom < visible.length)

  // Deduplicate redundant BOS lines at virtually identical bars or price levels
  const finalBOS: typeof rawBOS = []
  for (let i = rawBOS.length - 1; i >= 0; i--) {
    const b = rawBOS[i]
    const clashing = finalBOS.some(
      (existing) => Math.abs(existing.visBreak - b.visBreak) <= 3 ||
        (b.price > 0 && Math.abs(existing.price - b.price) / b.price < 0.0015)
    )
    if (!clashing) finalBOS.unshift(b)
    if (finalBOS.length >= 2) break
  }

  const backendCHoCH = context.smc?.choch
    ?.filter((c) => c.break_index <= rawEntryIdx)
    ?.map((c) => ({
      ...c,
      visFrom: c.from_index - startIdx,
      visBreak: c.break_index - startIdx,
    }))
    ?.filter((c) => c.visBreak >= 0 && c.visFrom < visible.length)

  const rawCHoCH = (backendCHoCH && backendCHoCH.length > 0)
    ? backendCHoCH
    : (fallbackSMC.choch || []).map((c) => ({
        ...c,
        visFrom: c.from_index - startIdx,
        visBreak: Math.min(c.break_index, fallbackEntryIdx) - startIdx,
      })).filter((c) => c.visBreak >= 0 && c.visFrom < visible.length)

  const finalCHoCH = rawCHoCH.slice(-1)

  const backendPools = context.smc?.liquidity_pools
    ?.filter((p) => p.index <= rawEntryIdx)
    ?.map((p) => ({
      ...p,
      visIdx: p.index - startIdx,
    }))
    ?.filter((p) => p.visIdx >= 0 && p.visIdx < visible.length)

  const rawPools = (backendPools && backendPools.length > 0)
    ? backendPools
    : (fallbackSMC.liquidity_pools || []).map((p) => ({
        ...p,
        visIdx: p.index - startIdx,
      })).filter((p) => p.visIdx >= 0 && p.visIdx < visible.length)

  // Keep at most 1 distinct Buy-side and 1 Sell-side pool
  const finalPools: typeof rawPools = []
  const hasBSL = rawPools.find((p) => p.type.includes('Buy-side'))
  const hasSSL = rawPools.find((p) => p.type.includes('Sell-side'))
  if (hasBSL) finalPools.push(hasBSL)
  if (hasSSL) finalPools.push(hasSSL)

  const rawTiming = context.smc?.trade_timing_analysis
  const tradeTimingAnalysis = rawTiming && !rawTiming.includes('limited without exact')
    ? rawTiming
    : `Historical market structure bounded strictly prior to entry (${entryPrice > 0 ? entryPrice.toFixed(2) : 'entry level'}).`

  const smc = {
    order_blocks: finalOBs,
    fvgs: finalFVGs,
    bos: finalBOS,
    choch: finalCHoCH,
    liquidity_pools: finalPools,
    channel: context.smc?.channel || fallbackSMC.channel,
    trade_timing_analysis: tradeTimingAnalysis,
  }

  const channel = smc.channel

  const linePoints = (values: number[]) => values.map((value, index) => `${x(index)},${y(value)}`).join(' ')

  const endCanvasIdx = Math.max(0, visible.length - 1)
  const channelPriceAt = (globalIndex: number, offset: number) =>
    channel ? channel.slope * globalIndex + channel.intercept + offset : 0
  const channelLeftGlobal = startIdx
  const channelRightGlobal = startIdx + endCanvasIdx
  const channelPolygonPoints = channel ? [
    `${x(0)},${y(channelPriceAt(channelLeftGlobal, channel.upper_offset))}`,
    `${x(endCanvasIdx)},${y(channelPriceAt(channelRightGlobal, channel.upper_offset))}`,
    `${x(endCanvasIdx)},${y(channelPriceAt(channelRightGlobal, channel.lower_offset))}`,
    `${x(0)},${y(channelPriceAt(channelLeftGlobal, channel.lower_offset))}`
  ].join(' ') : ''
  const channelUpper = channel ? {
    y1: y(channelPriceAt(channelLeftGlobal, channel.upper_offset)),
    y2: y(channelPriceAt(channelRightGlobal, channel.upper_offset)),
  } : null
  const channelLower = channel ? {
    y1: y(channelPriceAt(channelLeftGlobal, channel.lower_offset)),
    y2: y(channelPriceAt(channelRightGlobal, channel.lower_offset)),
  } : null
  const channelMid = channel ? {
    y1: y(channelPriceAt(channelLeftGlobal, channel.mid_offset)),
    y2: y(channelPriceAt(channelRightGlobal, channel.mid_offset)),
  } : null
  const barSpacing = chartWidth / Math.max(1, visible.length)

  const rrRatio = entryPrice > 0 && slPrice > 0 && tpPrice > 0 ? Math.abs(tpPrice - entryPrice) / Math.abs(entryPrice - slPrice) : 0

  return (
    <div className="trade-chart-panel">
      <div className="trade-chart-header">
        <div className="trade-chart-title">
          <span className="symbol-tag">{context.symbol || trade?.symbol || 'BTCUSDT'}</span>
          <span className="interval-tag">15m Perpetual • Bybit</span>
        </div>
        <div className="trade-sl-tp-inputs">
          <label className="sl-tp-field sl">
            <span>SL</span>
            <input type="number" step="any" placeholder="SL Price" value={slInput} onChange={(e) => setSlInput(e.target.value)} />
          </label>
          <label className="sl-tp-field tp">
            <span>TP</span>
            <input type="number" step="any" placeholder="TP Price" value={tpInput} onChange={(e) => setTpInput(e.target.value)} />
          </label>
          {rrRatio > 0 && <span className="rr-badge">R:R 1:{rrRatio.toFixed(2)}</span>}
        </div>
        <div className="chart-controls">
          <button className={`toggle-btn ${showSMC ? 'active' : ''}`} type="button" onClick={() => setShowSMC(!showSMC)}>SMC Overlay</button>
          <button className={`toggle-btn ${showChannel ? 'active' : ''}`} type="button" onClick={() => setShowChannel(!showChannel)}>Channel</button>
          <button className={`toggle-btn ${showEMAs ? 'active' : ''}`} type="button" onClick={() => setShowEMAs(!showEMAs)}>EMAs</button>
          <button type="button" onClick={() => setWindowStart(Math.max(0, startIdx - panStep))}>◀ Left</button>
          <button type="button" onClick={() => setWindowStart(null)} className="primary-ctrl">Center Trade</button>
          <button type="button" onClick={() => setWindowStart(Math.min(maxStart, startIdx + panStep))}>Right ▶</button>
          <button type="button" onClick={() => {
            const next = Math.max(20, visibleCount - 15)
            const mid = startIdx + Math.floor(visible.length / 2)
            setVisibleCount(next)
            setWindowStart(Math.max(0, mid - Math.floor(next / 2)))
          }}>Zoom in</button>
          <button type="button" onClick={() => {
            const next = Math.min(candles.length, visibleCount + 15)
            const mid = startIdx + Math.floor(visible.length / 2)
            setVisibleCount(next)
            setWindowStart(Math.max(0, mid - Math.floor(next / 2)))
          }}>Zoom out</button>
        </div>
      </div>

      <div className="trade-chart-stage">
        {showSMC && (
          <div className="smc-legend-card">
            <div className="smc-card-title">Smart Money Strategy</div>
            <div className="smc-card-subtitle">SMC Overlay</div>
            <div className="smc-card-items">
              <span className="smc-key ob-bearish-key"><i /> Bearish OB</span>
              <span className="smc-key ob-bullish-key"><i /> Bullish OB</span>
              <span className="smc-key fvg-key"><i /> FVG</span>
              <span className="smc-key channel-key"><i /> Parallel Channel</span>
            </div>
          </div>
        )}

        <svg className="trade-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Smart Money Strategy Chart">
          <defs>
            <pattern id="fvg-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" stroke="#f59e0b" strokeWidth="1.2" opacity="0.3" />
            </pattern>
            <clipPath id="plot-clip">
              <rect x={padding.left} y={padding.top} width={chartWidth} height={chartHeight} />
            </clipPath>
            <marker id="arrow-bos" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M 0 2 L 7 5 L 0 8 z" fill="#cbd5e1" />
            </marker>
          </defs>

          <line className="chart-gridline" x1={padding.left} x2={width - padding.right} y1={padding.top} y2={padding.top} />
          <line className="chart-gridline" x1={padding.left} x2={width - padding.right} y1={height / 2} y2={height / 2} />
          <line className="chart-gridline" x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />

          {showChannel && channel && channelUpper && channelLower && channelMid && (
            <g className="parallel-channel-group" clipPath="url(#plot-clip)">
              <polygon points={channelPolygonPoints} fill="rgba(45, 212, 191, 0.08)" stroke="none" />
              <line x1={x(0)} y1={channelUpper.y1} x2={x(endCanvasIdx)} y2={channelUpper.y2} stroke="#f87171" strokeWidth="1.2" strokeOpacity="0.75" />
              <line x1={x(0)} y1={channelLower.y1} x2={x(endCanvasIdx)} y2={channelLower.y2} stroke="#34d399" strokeWidth="1.2" strokeOpacity="0.75" />
              <line x1={x(0)} y1={channelMid.y1} x2={x(endCanvasIdx)} y2={channelMid.y2} stroke="#94a3b8" strokeWidth="1" strokeDasharray="3 3" strokeOpacity="0.6" />
            </g>
          )}

          {/* 2. Order Blocks (Background Zones) */}
          {showSMC && smc.order_blocks?.map((ob, idx) => {
            const visS = typeof ob.visStart === 'number' ? ob.visStart : ob.start_index - startIdx
            const visE = typeof ob.visEnd === 'number' ? ob.visEnd : ob.end_index - startIdx
            if (visE < 0 || visS >= visible.length) return null
            const maxVisBar = entryIndex >= 0 ? entryIndex : visible.length - 1
            if (visS > maxVisBar) return null
            const startX = x(Math.max(0, visS))
            const endX = x(Math.min(maxVisBar, Math.max(visS + 1, visE)))
            const obWidth = Math.max(barSpacing * 0.7, endX - startX)
            const topY = y(ob.top)
            const bottomY = y(ob.bottom)
            const obHeight = Math.max(2, bottomY - topY)
            if (obWidth < 2 || obHeight < 2) return null
            const isBullish = ob.type === 'Bullish OB'
            const badgeW = obWidth >= 72 ? 52 : 28
            const badgeText = obWidth >= 72 ? (isBullish ? '+OB Bull' : '-OB Bear') : (isBullish ? '+OB' : '-OB')
            const showBadge = obWidth >= 28 && obHeight >= 14

            return (
              <g key={`ob-${idx}`} className={`order-block ${isBullish ? 'bullish' : 'bearish'}`} clipPath="url(#plot-clip)">
                <rect x={startX} y={topY} width={obWidth} height={obHeight} fill={isBullish ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.12)'} stroke={isBullish ? 'rgba(34, 197, 94, 0.55)' : 'rgba(239, 68, 68, 0.55)'} strokeWidth="1" rx="2" />
                {showBadge && (
                  <>
                    <rect x={startX + 2} y={topY + 2} width={badgeW} height="12" rx="2" fill={isBullish ? 'rgba(20, 83, 45, 0.88)' : 'rgba(127, 29, 29, 0.88)'} stroke={isBullish ? 'rgba(34, 197, 94, 0.7)' : 'rgba(239, 68, 68, 0.7)'} strokeWidth="0.5" />
                    <text x={startX + 2 + badgeW / 2} y={topY + 8} className="smc-badge-text bold" fontSize="8.5" fontFamily="'DM Mono', monospace" fontWeight="700" textAnchor="middle" dominantBaseline="central" fill="#ffffff">
                      {badgeText}
                    </text>
                  </>
                )}
              </g>
            )
          })}

          {/* 3. Fair Value Gaps (Background Zones) */}
          {showSMC && smc.fvgs?.map((fvg, idx) => {
            const visS = typeof fvg.visStart === 'number' ? fvg.visStart : fvg.start_index - startIdx
            const visE = typeof fvg.visEnd === 'number' ? fvg.visEnd : fvg.end_index - startIdx
            if (visE < 0 || visS >= visible.length) return null
            const maxVisBar = entryIndex >= 0 ? entryIndex : visible.length - 1
            if (visS > maxVisBar) return null
            const startX = x(Math.max(0, visS))
            const endX = x(Math.min(maxVisBar, Math.max(visS + 1, visE)))
            const fvgWidth = Math.max(barSpacing * 0.7, endX - startX)
            const topY = y(fvg.top)
            const bottomY = y(fvg.bottom)
            const fvgHeight = Math.max(2, bottomY - topY)
            if (fvgWidth < 2 || fvgHeight < 2) return null
            const showBadge = fvgWidth >= 28 && fvgHeight >= 14

            return (
              <g key={`fvg-${idx}`} className="fvg-group" clipPath="url(#plot-clip)">
                <rect x={startX} y={topY} width={fvgWidth} height={fvgHeight} fill="rgba(245, 158, 11, 0.08)" rx="2" />
                <rect x={startX} y={topY} width={fvgWidth} height={fvgHeight} fill="url(#fvg-hatch)" stroke="rgba(245, 158, 11, 0.45)" strokeWidth="1" strokeDasharray="3 2" rx="2" />
                {showBadge && (
                  <>
                    <rect x={startX + 2} y={topY + Math.max(2, (fvgHeight - 12) / 2)} width="26" height="12" rx="2" fill="rgba(120, 53, 15, 0.88)" stroke="#f59e0b" strokeWidth="0.5" />
                    <text x={startX + 15} y={topY + Math.max(2, (fvgHeight - 12) / 2) + 6} className="smc-badge-text bold" fontSize="8.5" fontFamily="'DM Mono', monospace" fontWeight="700" textAnchor="middle" dominantBaseline="central" fill="#fef3c7">
                      FVG
                    </text>
                  </>
                )}
              </g>
            )
          })}

          {/* 4. Candlesticks (Midground) */}
          {visible.map((candle, index) => {
            const open = Number(candle.open)
            const close = Number(candle.close)
            const candleWidth = Math.max(3, (chartWidth / visible.length) * 0.55)
            const cx = x(index)
            const isBullish = close >= open

            return (
              <g key={`candle-${candle.timestamp}-${index}`} className="candle-group">
                <line className={isBullish ? 'candle-wick bullish' : 'candle-wick bearish'} x1={cx} x2={cx} y1={y(Number(candle.high))} y2={y(Number(candle.low))} />
                <rect className={isBullish ? 'candle-body bullish' : 'candle-body bearish'} x={cx - candleWidth / 2} y={y(Math.max(open, close))} width={candleWidth} height={Math.max(1, Math.abs(y(open) - y(close)))} rx="0.5" />
              </g>
            )
          })}

          {/* 5. EMAs */}
          {showEMAs && (
            <>
              <polyline className="ema-line ema20-line" points={linePoints(ema20)} stroke="#38bdf8" strokeWidth="1.5" fill="none" />
              <polyline className="ema-line ema50-line" points={linePoints(ema50)} stroke="#a855f7" strokeWidth="1.5" fill="none" />
              <polyline className="ema-line ema30-line" points={linePoints(ema30)} stroke="#ec4899" strokeWidth="1.5" strokeDasharray="2 2" fill="none" />
            </>
          )}

          {/* 6. Break of Structure (BOS) Overlays */}
          {showSMC && smc.bos?.map((item, idx) => {
            const visF = typeof item.visFrom === 'number' ? item.visFrom : item.from_index - startIdx
            const visB = typeof item.visBreak === 'number' ? item.visBreak : item.break_index - startIdx
            if (visB < 0 || visF >= visible.length) return null
            const maxVisBar = entryIndex >= 0 ? entryIndex : visible.length - 1
            if (visF > maxVisBar) return null
            const x1 = x(Math.max(0, visF))
            const x2 = Math.max(x1 + 25, x(Math.min(maxVisBar, visB)))
            const yPos = y(item.price)
            const midX = (x1 + x2) / 2
            const isBull = item.type?.includes('Bullish')
            const bosText = isBull ? '+BOS' : '-BOS'
            const showBadge = x2 - x1 >= 36

            return (
              <g key={`bos-${idx}`} className="bos-group">
                <line x1={x1} y1={yPos} x2={x2} y2={yPos} stroke="rgba(226, 232, 240, 0.7)" strokeWidth="1.2" strokeDasharray="3 2" markerEnd="url(#arrow-bos)" />
                {showBadge && (
                  <>
                    <rect x={midX - 16} y={yPos - 6} width="32" height="12" rx="2.5" fill="rgba(15, 23, 42, 0.88)" stroke="rgba(148, 163, 184, 0.6)" strokeWidth="0.75" />
                    <text x={midX} y={yPos} className="smc-badge-text bold" fontSize="8.5" fontFamily="'DM Mono', monospace" fontWeight="700" textAnchor="middle" dominantBaseline="central" fill="#f8fafc">
                      {bosText}
                    </text>
                  </>
                )}
              </g>
            )
          })}

          {/* 7. Change of Character (CHoCH) Overlays */}
          {showSMC && smc.choch?.map((item, idx) => {
            const visF = typeof item.visFrom === 'number' ? item.visFrom : item.from_index - startIdx
            const visB = typeof item.visBreak === 'number' ? item.visBreak : item.break_index - startIdx
            if (visB < 0 || visF >= visible.length) return null
            const maxVisBar = entryIndex >= 0 ? entryIndex : visible.length - 1
            if (visF > maxVisBar) return null
            const x1 = x(Math.max(0, visF))
            const x2 = Math.max(x1 + 35, x(Math.min(maxVisBar, visB)))
            const yPos = y(item.price)
            const midX = (x1 + x2) / 2
            const isBull = item.type?.includes('Bullish')
            const chochText = isBull ? '+CHoCH' : '-CHoCH'
            const showBadge = x2 - x1 >= 44

            return (
              <g key={`choch-${idx}`} className="choch-group">
                <line x1={x1} y1={yPos} x2={x2} y2={yPos} stroke="#38bdf8" strokeWidth="1.2" strokeDasharray="4 3" />
                {showBadge && (
                  <>
                    <rect x={midX - 21} y={yPos - 6} width="42" height="12" rx="2.5" fill="rgba(15, 23, 42, 0.9)" stroke="#38bdf8" strokeWidth="0.75" />
                    <text x={midX} y={yPos} className="smc-badge-text bold" fontSize="8.5" fontFamily="'DM Mono', monospace" fontWeight="700" textAnchor="middle" dominantBaseline="central" fill="#38bdf8">
                      {chochText}
                    </text>
                  </>
                )}
              </g>
            )
          })}

          {/* 8. Liquidity Pools (BSL / SSL) */}
          {showSMC && smc.liquidity_pools?.map((pool, idx) => {
            const visI = typeof pool.visIdx === 'number' ? pool.visIdx : pool.index - startIdx
            if (visI < 0 || visI >= visible.length) return null
            const maxVisBar = entryIndex >= 0 ? entryIndex : visible.length - 1
            if (visI > maxVisBar) return null
            const posX = x(Math.max(0, Math.min(maxVisBar, visI)))
            const posY = y(pool.price)
            const isBSL = pool.type.includes('Buy-side') || pool.label?.includes('BSL')
            const poolLabel = isBSL ? '💧 BSL' : '💧 SSL'
            const lineLeft = Math.max(padding.left, posX - 15)
            const lineRight = Math.min(width - padding.right, posX + 40)

            return (
              <g key={`pool-${idx}`} className="liquidity-pool-group">
                <line x1={lineLeft} y1={posY} x2={lineRight} y2={posY} stroke={isBSL ? 'rgba(56, 189, 248, 0.6)' : 'rgba(244, 63, 94, 0.6)'} strokeWidth="1.2" strokeDasharray="3 2" />
                <rect x={posX - 21} y={isBSL ? posY - 14 : posY + 2} width="42" height="12" rx="2.5" fill="rgba(15, 23, 42, 0.92)" stroke={isBSL ? '#38bdf8' : '#f43f5e'} strokeWidth="0.75" />
                <text x={posX} y={isBSL ? posY - 8 : posY + 8} className="smc-badge-text bold" fontSize="8" fontFamily="'DM Mono', monospace" fontWeight="700" textAnchor="middle" dominantBaseline="central" fill={isBSL ? '#7dd3fc' : '#fda4af'}>
                  {poolLabel}
                </text>
              </g>
            )
          })}

          {/* Horizontal Price Target Lines: ENTRY, EXIT, SL, TP */}
          {entryPrice > 0 && (
            <g className="price-level-line entry-price">
              <line x1={padding.left} x2={width - padding.right} y1={y(entryPrice)} y2={y(entryPrice)} stroke="#22c55e" strokeWidth="1.5" strokeDasharray="5 3" />
              <rect x={width - padding.right + 4} y={y(entryPrice) - 9} width="90" height="18" rx="3" fill="#15803d" />
              <text x={width - padding.right + 49} y={y(entryPrice) + 3} textAnchor="middle" fill="#ffffff" className="price-badge-text bold">
                ENTRY: {entryPrice.toFixed(2)}
              </text>
            </g>
          )}

          {exitPrice > 0 && (
            <g className="price-level-line exit-price">
              <line x1={padding.left} x2={width - padding.right} y1={y(exitPrice)} y2={y(exitPrice)} stroke="#ef4444" strokeWidth="1.5" strokeDasharray="5 3" />
              <rect x={width - padding.right + 4} y={y(exitPrice) - 9} width="90" height="18" rx="3" fill="#b91c1c" />
              <text x={width - padding.right + 49} y={y(exitPrice) + 3} textAnchor="middle" fill="#ffffff" className="price-badge-text bold">
                EXIT: {exitPrice.toFixed(2)}
              </text>
            </g>
          )}

          {slPrice > 0 && (
            <g className="price-level-line sl-price">
              <line x1={padding.left} x2={width - padding.right} y1={y(slPrice)} y2={y(slPrice)} stroke="#f43f5e" strokeWidth="1.5" strokeDasharray="4 2" />
              <rect x={width - padding.right + 4} y={y(slPrice) - 9} width="90" height="18" rx="3" fill="#be123c" />
              <text x={width - padding.right + 49} y={y(slPrice) + 3} textAnchor="middle" fill="#ffffff" className="price-badge-text bold">
                SL: {slPrice.toFixed(2)}
              </text>
            </g>
          )}

          {tpPrice > 0 && (
            <g className="price-level-line tp-price">
              <line x1={padding.left} x2={width - padding.right} y1={y(tpPrice)} y2={y(tpPrice)} stroke="#10b981" strokeWidth="1.5" strokeDasharray="4 2" />
              <rect x={width - padding.right + 4} y={y(tpPrice) - 9} width="90" height="18" rx="3" fill="#047857" />
              <text x={width - padding.right + 49} y={y(tpPrice) + 3} textAnchor="middle" fill="#ffffff" className="price-badge-text bold">
                TP: {tpPrice.toFixed(2)}
              </text>
            </g>
          )}

          {entryIndex >= 0 && visible[entryIndex] && (
            <g className="candle-callout entry-callout">
              <line className="trade-marker entry-marker" x1={x(entryIndex)} x2={x(entryIndex)} y1={padding.top} y2={height - padding.bottom} stroke="#22c55e" strokeWidth="1.5" strokeDasharray="4 2" />
              <polygon points={`${x(entryIndex) - 6},${y(Number(visible[entryIndex].low)) + 14} ${x(entryIndex) + 6},${y(Number(visible[entryIndex].low)) + 14} ${x(entryIndex)},${y(Number(visible[entryIndex].low)) + 4}`} fill="#22c55e" />
              <rect x={x(entryIndex) - 28} y={y(Number(visible[entryIndex].low)) + 15} width="56" height="16" rx="3" fill="#15803d" />
              <text x={x(entryIndex)} y={y(Number(visible[entryIndex].low)) + 27} className="marker-badge-text bold" textAnchor="middle" fill="#ffffff">
                Entry
              </text>
            </g>
          )}

          {exitIndex >= 0 && visible[exitIndex] && (
            <g className="candle-callout exit-callout">
              <line className="trade-marker exit-marker" x1={x(exitIndex)} x2={x(exitIndex)} y1={padding.top} y2={height - padding.bottom} stroke="#ef4444" strokeWidth="1.5" strokeDasharray="4 2" />
              <polygon points={`${x(exitIndex) - 6},${y(Number(visible[exitIndex].high)) - 14} ${x(exitIndex) + 6},${y(Number(visible[exitIndex].high)) - 14} ${x(exitIndex)},${y(Number(visible[exitIndex].high)) - 4}`} fill="#ef4444" />
              <rect x={x(exitIndex) - 24} y={y(Number(visible[exitIndex].high)) - 30} width="48" height="16" rx="3" fill="#b91c1c" />
              <text x={x(exitIndex)} y={y(Number(visible[exitIndex].high)) - 18} className="marker-badge-text bold" textAnchor="middle" fill="#ffffff">
                Exit
              </text>
            </g>
          )}

          {entryIndex >= 0 && exitIndex >= 0 && entryIndex !== exitIndex && visible[entryIndex] && visible[exitIndex] && (
            <line
              clipPath="url(#plot-clip)"
              x1={x(entryIndex)}
              y1={y(Number(lifecycle?.entry_price || visible[entryIndex]?.close || entryPrice))}
              x2={x(exitIndex)}
              y2={y(Number(lifecycle?.exit_price || visible[exitIndex]?.close || exitPrice))}
              stroke={Number(trade?.realized_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444'}
              strokeWidth="2"
              strokeDasharray="3 3"
            />
          )}

          <text className="chart-label" x={padding.left - 8} y={padding.top + 4} textAnchor="end" fill="#94a3b8">{maximum.toFixed(2)}</text>
          <text className="chart-label" x={padding.left - 8} y={(padding.top + height - padding.bottom) / 2 + 4} textAnchor="end" fill="#64748b">{((maximum + minimum) / 2).toFixed(2)}</text>
          <text className="chart-label" x={padding.left - 8} y={height - padding.bottom + 4} textAnchor="end" fill="#94a3b8">{minimum.toFixed(2)}</text>
        </svg>
      </div>

      <div className="chart-footer-strip">
        <div className="chart-marker-key">
          <span><i className="entry-key" /> Entry</span>
          <span><i className="exit-key" /> Exit</span>
          {showEMAs && <span><i className="ema20-key" /> EMA20</span>}
          {showEMAs && <span><i className="ema50-key" /> EMA50</span>}
          {showEMAs && <span><i className="ema30-key" /> EMA30</span>}
        </div>
        {smc.trade_timing_analysis && (
          <div className="timing-analysis-note">
            ⚡ <strong>Trade Timing Analysis:</strong> {smc.trade_timing_analysis}
          </div>
        )}
      </div>
    </div>
  )
}

function App() {
  const [error, setError] = useState('')
  const [executions, setExecutions] = useState<BybitExecution[]>([])
  const [isSyncing, setIsSyncing] = useState(false)
  const [trades, setTrades] = useState<TradeSummary[]>([])
  const [metrics, setMetrics] = useState<AccountMetrics | null>(null)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<AIAnalysis | null>(null)
  const [analyzedTrade, setAnalyzedTrade] = useState<TradeSummary | null>(null)
  const [chartContext, setChartContext] = useState<ChartContext | null>(null)
  const [tradeLifecycle, setTradeLifecycle] = useState<TradeLifecycle | null>(null)
  const [relevantRules, setRelevantRules] = useState<KnowledgeRecord[]>([])
  const [analyzingOrderId, setAnalyzingOrderId] = useState<string | null>(null)
  const [knowledgeForm, setKnowledgeForm] = useState<KnowledgeFormState>(initialKnowledge)
  const [knowledgeRecords, setKnowledgeRecords] = useState<KnowledgeRecord[]>([])
  const [isSavingKnowledge, setIsSavingKnowledge] = useState(false)

  const updateKnowledge = <Key extends keyof KnowledgeFormState>(key: Key, value: KnowledgeFormState[Key]) => {
    setKnowledgeForm((current) => ({ ...current, [key]: value }))
  }

  const loadKnowledge = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/v1/knowledge?limit=8`)
      if (!response.ok) throw new Error('Could not load trading knowledge.')
      const records = await response.json() as KnowledgeRecord[]
      setKnowledgeRecords(records)
    } catch {
      setKnowledgeRecords([])
    }
  }

  const saveKnowledge = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setIsSavingKnowledge(true)
    try {
      const response = await fetch(`${apiUrl}/api/v1/knowledge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: knowledgeForm.title,
          content: knowledgeForm.content,
          tags: knowledgeForm.tags.split(',').map((tag) => tag.trim()).filter(Boolean),
          category: knowledgeForm.category,
        }),
      })
      const payload = await response.json() as { status?: string; record?: KnowledgeRecord; detail?: string }
      if (!response.ok) throw new Error(payload.detail ?? 'Could not save the trading rule.')
      setKnowledgeForm(initialKnowledge)
      if (payload.record) {
        setKnowledgeRecords((current) => [payload.record as KnowledgeRecord, ...current])
      }
      await loadKnowledge()
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Unable to save the knowledge entry.')
    } finally {
      setIsSavingKnowledge(false)
    }
  }

  const selectedDataQuery = (limit: number) => {
    const params = new URLSearchParams({ limit: String(limit), timezone_offset_minutes: String(-new Date().getTimezoneOffset()) })
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    return params.toString()
  }

  useEffect(() => {
    void loadKnowledge()
    fetch(`${apiUrl}/api/v1/history?${selectedDataQuery(25)}`)
      .then((response) => response.ok ? response.json() : [])
      .then((history) => setExecutions(history as BybitExecution[]))
      .catch(() => undefined)
    fetch(`${apiUrl}/api/v1/trades?${selectedDataQuery(500)}`)
      .then((response) => response.ok ? response.json() : [])
      .then((summary) => setTrades(summary as TradeSummary[]))
      .catch(() => undefined)
    fetch(`${apiUrl}/api/v1/metrics?${selectedDataQuery(500)}`)
      .then((response) => response.ok ? response.json() : null)
      .then((summary) => setMetrics(summary as AccountMetrics | null))
      .catch(() => undefined)
  }, [])

  const formatDate = (value: string) => {
    const timestamp = /^\d+$/.test(value) ? Number(value) : value
    return new Date(timestamp).toLocaleString()
  }

  const positionDirection = (side: TradeSummary['side']) => {
    if (side === 'Sell') return 'Long'
    if (side === 'Buy') return 'Short'
    return 'Mixed'
  }

  const statusClass = (status: TradeReview['rule_status']) => status.replaceAll(' ', '-')

  const syncHistory = async (loadMore = false) => {
    setIsSyncing(true)
    setError('')
    try {
      const params = new URLSearchParams({ limit: '50' })
      params.set('timezone_offset_minutes', String(-new Date().getTimezoneOffset()))
      if (startDate) params.set('start_date', startDate)
      if (endDate) params.set('end_date', endDate)
      if (loadMore && nextCursor) params.set('cursor', nextCursor)
      const response = await fetch(`${apiUrl}/api/v1/sync/bybit?${params.toString()}`, { method: 'POST' })
      const payload = await response.json() as { executions?: BybitExecution[]; persisted?: boolean; next_cursor?: string | null; detail?: string }
      if (!response.ok) throw new Error(payload.detail ?? 'Could not sync Bybit history.')
      setExecutions((current) => loadMore ? [...current, ...(payload.executions ?? [])] : (payload.executions ?? []))
      setNextCursor(payload.next_cursor ?? null)
      const summaryResponse = await fetch(`${apiUrl}/api/v1/trades?${selectedDataQuery(500)}`)
      if (summaryResponse.ok) setTrades(await summaryResponse.json() as TradeSummary[])
      const metricsResponse = await fetch(`${apiUrl}/api/v1/metrics?${selectedDataQuery(500)}`)
      if (metricsResponse.ok) setMetrics(await metricsResponse.json() as AccountMetrics)
      if (!payload.persisted) setError('Synced from Bybit, but Supabase is not configured yet.')
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : 'Unable to sync Bybit history.')
    } finally {
      setIsSyncing(false)
    }
  }

  const analyzeTrade = async (trade: TradeSummary) => {
    setAnalyzingOrderId(trade.order_id)
    setError('')
    try {
      const params = new URLSearchParams(selectedDataQuery(500))
      params.set('order_id', trade.order_id)
      const response = await fetch(`${apiUrl}/api/v1/analyze-history?${params.toString()}`, { method: 'POST' })
      const payload = await response.json() as AnalysisPayload
      if (!response.ok || !payload.analysis) throw new Error(payload.detail ?? 'Could not analyze this trade.')
      const retrievedRules = payload.retrieved_knowledge ?? []
      const normalizedAnalysis = normalizeAnalysis(payload.analysis)
      const ruleContext = retrievedRules.length ? retrievedRules : knowledgeRecords
      if (normalizedAnalysis.trade_reviews.length === 0) {
        normalizedAnalysis.trade_reviews = buildFallbackTradeReviews([trade], ruleContext)
      }
      setAnalysis(normalizedAnalysis)
      setAnalyzedTrade(trade)
      setChartContext(payload.chart_context ?? null)
      setTradeLifecycle(payload.trade_lifecycle ?? null)
      setRelevantRules(ruleContext)
    } catch (analysisError) {
      setError(analysisError instanceof Error ? analysisError.message : 'Unable to analyze this trade.')
    } finally {
      setAnalyzingOrderId(null)
    }
  }

  return (
    <main className="journal-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><Activity size={17} /></span>
          <span>Ledger / AI</span>
        </div>
        <div className="connection">
          <span className="status-dot" /> API ready <span className="mono">{apiUrl.replace(/^https?:\/\//, '')}</span>
        </div>
      </header>

      <section className="intro">
        <div>
          <p className="eyebrow">Trade intelligence / 01</p>
          <h1>Make the next trade<br /><em>more deliberate.</em></h1>
        </div>
        <p className="intro-copy">Capture the facts while they are fresh. The journal turns each position into a clearer feedback loop.</p>
      </section>

      {metrics && (
        <section className="metrics-strip">
          <div className="metric">
            <span className="eyebrow">Net realized P&L</span>
            <strong className={Number(metrics.net_pnl) >= 0 ? 'positive' : 'negative'}>{metrics.net_pnl} USDT</strong>
            <small>After fees</small>
          </div>
          <div className="metric">
            <span className="eyebrow">Closed P&L win rate</span>
            <strong>{metrics.win_rate}%</strong>
            <small>{metrics.winners} wins / {metrics.losers} losses</small>
          </div>
          <div className="metric">
            <span className="eyebrow">Total fees</span>
            <strong>{metrics.fees} USDT</strong>
            <small>{metrics.fill_count} fills</small>
          </div>
          <div className="metric">
            <span className="eyebrow">Order records</span>
            <strong>{metrics.trade_count}</strong>
            <small>{metrics.closed_trades} closed P&L events</small>
          </div>
        </section>
      )}

      {analysis && (
        <section className="analysis-panel">
          <div className="analysis-header">
            <div>
              <p className="eyebrow">AI journal review</p>
              <h2>{analyzedTrade?.symbol ?? 'Trade'} rule review</h2>
            </div>
            <span className="analysis-badge">Saved to Supabase</span>
          </div>

          <p className="analysis-summary">{stripFillFeePreamble(analysis.summary)}</p>

          <TradeChart context={chartContext} lifecycle={tradeLifecycle} trade={analyzedTrade} />

          <div className="review-stack">
            <details className="review-details">
              <summary>Chart evidence</summary>
              <div className="review-details-body">
                {reviewParagraphs(analysis.chart_review).map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
              </div>
            </details>

            <details className="review-details">
              <summary>Technical analysis</summary>
              <div className="review-details-body">
                {reviewParagraphs(analysis.technical_review).map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
              </div>
            </details>

            {relevantRules.length > 0 && (
              <details className="review-details">
                <summary>Relevant rules used</summary>
                <div className="review-details-body relevant-rules-list">
                  {relevantRules.map((rule) => (
                    <article className="relevant-rule" key={rule.id ?? rule.title}>
                      <strong>{rule.title}</strong>
                      <p>{rule.content}</p>
                      <div className="knowledge-tags">
                        {rule.tags.map((tag) => (
                          <span key={`${rule.id ?? rule.title}-${tag}`} className="tag">{tag}</span>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </details>
            )}
          </div>

          {analysis.trade_reviews.length > 0 && (
            <div className="trade-review-panel">
              <p className="eyebrow">Rule decision for this trade</p>
              <div className="trade-review-list">
                {analysis.trade_reviews.map((review) => (
                  <div className={`trade-review ${review.rule_status}`} key={`${review.order_id}-${review.symbol}`}>
                    <div className="trade-review-header">
                      <strong>{review.symbol}</strong>
                      <span className={`trade-review-status ${statusClass(review.rule_status)}`}>{review.rule_status}</span>
                      <span className="compliance-score">{review.compliance_score}%</span>
                      <span className="review-confidence">Confidence {Math.round(review.confidence * 100)}%</span>
                    </div>
                    <p className="trade-review-notes">{review.notes}</p>
                    <div className="knowledge-tags">
                      {review.matched_rules.map((rule) => (
                        <span key={`${review.order_id}-${rule}`} className="tag">{rule}</span>
                      ))}
                    </div>
                    <details className="review-details">
                      <summary>Evidence used and missing</summary>
                      <div className="review-details-body review-evidence-grid">
                        <div>
                          <span className="eyebrow">Evidence used</span>
                          <ul>
                            {review.evidence.map((item) => <li key={item}>{item}</li>)}
                          </ul>
                        </div>
                        <div>
                          <span className="eyebrow">Missing evidence</span>
                          <ul>
                            {review.missing_evidence.map((item) => <li key={item}>{item}</li>)}
                          </ul>
                        </div>
                      </div>
                    </details>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      <section className="knowledge-grid">
        <div className="knowledge-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Personal rulebook</p>
              <h2>Trading rules</h2>
            </div>
            <span className="step-count">{knowledgeRecords.length} saved</span>
          </div>
          <div className="knowledge-list">
            {knowledgeRecords.length ? (
              knowledgeRecords.map((record) => (
                <article className="knowledge-card" key={record.id ?? `${record.title}-${record.category}`}>
                  <div className="knowledge-card-header">
                    <h3>{record.title}</h3>
                    {typeof record.relevance_score === 'number' && (
                      <span className="relevance-badge">{record.relevance_score.toFixed(1)} score</span>
                    )}
                  </div>
                  <p>{record.content}</p>
                  <div className="knowledge-tags">
                    {record.tags.map((tag) => (
                      <span key={`${record.id ?? record.title}-${tag}`} className="tag">{tag}</span>
                    ))}
                  </div>
                </article>
              ))
            ) : (
              <div className="history-empty"><NotebookPen size={18} /> No trading rules saved yet. Add one to ground future AI reviews.</div>
            )}
          </div>
        </div>

        <form className="knowledge-form-panel" onSubmit={saveKnowledge}>
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Add rule</p>
              <h2>Capture a rule</h2>
            </div>
            <span className="step-count">RAG</span>
          </div>

          <label>
            Title
            <input value={knowledgeForm.title} onChange={(event) => updateKnowledge('title', event.target.value)} placeholder="e.g. Risk cap on loser streaks" required />
          </label>

          <label>
            Rule content
            <textarea value={knowledgeForm.content} onChange={(event) => updateKnowledge('content', event.target.value)} placeholder="Document the process, risk limit, setup criteria, or behavior you want the AI to remember." rows={6} required />
          </label>

          <div className="field-row knowledge-row">
            <label>
              Tags
              <input value={knowledgeForm.tags} onChange={(event) => updateKnowledge('tags', event.target.value)} placeholder="risk, discipline, fees" />
            </label>
            <label>
              Category
              <select value={knowledgeForm.category} onChange={(event) => updateKnowledge('category', event.target.value)}>
                <option value="trading_rule">Trading rule</option>
                <option value="risk_rule">Risk rule</option>
                <option value="portfolio_rule">Portfolio rule</option>
                <option value="execution_rule">Execution rule</option>
              </select>
            </label>
          </div>

          {error && <p className="error-message">{error}</p>}

          <button className="submit-button" type="submit" disabled={isSavingKnowledge}>
            {isSavingKnowledge ? <LoaderCircle className="spin" size={17} /> : <NotebookPen size={17} />}
            {' '}
            {isSavingKnowledge ? 'Saving rule...' : 'Save rule'}
            <ArrowUpRight size={17} />
          </button>
        </form>
      </section>

      <section className="history-panel">
        <div className="history-heading">
          <div>
            <p className="eyebrow">Bybit mainnet / completed outcomes</p>
            <h2>Closed trades</h2>
          </div>
          <div className="sync-actions">
            <label className="date-field">
              <CalendarDays size={14} /> Start date
              <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
            </label>
            <label className="date-field">
              End date
              <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
            </label>
            <button className="sync-button" type="button" onClick={() => syncHistory()} disabled={isSyncing}>
              {isSyncing ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}
              {' '}
              {isSyncing ? 'Syncing...' : 'Sync range'}
            </button>
          </div>
        </div>

        {trades.filter((trade) => Number(trade.realized_pnl) !== 0).length ? (
          <div className="history-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Position</th>
                  <th>Realized P&L</th>
                  <th>Entry</th>
                  <th>SL</th>
                  <th>TP</th>
                  <th>Executed</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {trades.filter((trade) => Number(trade.realized_pnl) !== 0).map((trade) => (
                  <tr key={trade.order_id}>
                    <td>
                      <strong>{trade.symbol}</strong>
                    </td>
                    <td>
                      <span className={positionDirection(trade.side) === 'Long' ? 'side buy' : positionDirection(trade.side) === 'Short' ? 'side sell' : 'side mixed'}>{positionDirection(trade.side)}</span>
                    </td>
                    <td className={Number(trade.realized_pnl) >= 0 ? 'pnl positive' : 'pnl negative'}>{trade.realized_pnl}</td>
                    <td>{formatAlignedPrice(trade.entry_price, trade.stop_loss, trade.take_profit)}</td>
                    <td>{Number(trade.stop_loss) ? trade.stop_loss : '—'}</td>
                    <td>{Number(trade.take_profit) ? trade.take_profit : '—'}</td>
                    <td>{formatDate(trade.executed_at)}</td>
                    <td>
                      <button className="row-action-button" type="button" onClick={() => void analyzeTrade(trade)} disabled={analyzingOrderId !== null}>
                        {analyzingOrderId === trade.order_id ? <LoaderCircle className="spin" size={14} /> : 'Analyze'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="history-empty"><Database size={18} /> No closed trades in this range.</div>
        )}

        {nextCursor && (
          <button className="load-more-button" type="button" onClick={() => syncHistory(true)} disabled={isSyncing}>
            {isSyncing ? 'Loading...' : 'Load more history'}
          </button>
        )}
      </section>

      <section className="history-panel raw-history">
        <div className="history-heading">
          <div>
            <p className="eyebrow">Fill detail</p>
            <h2>Execution history</h2>
          </div>
          <span className="step-count">{executions.length} fills</span>
        </div>

        {executions.length ? (
          <div className="history-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Quantity</th>
                  <th>Price</th>
                  <th>Fee</th>
                  <th>Executed</th>
                </tr>
              </thead>
              <tbody>
                {executions.map((execution) => (
                  <tr key={execution.external_id}>
                    <td>
                      <strong>{execution.symbol}</strong>
                      <span className="order-id">{execution.order_id?.slice(0, 8) ?? 'manual'}</span>
                    </td>
                    <td>
                      <span className={execution.side === 'Buy' ? 'side buy' : 'side sell'}>{execution.side}</span>
                    </td>
                    <td>{execution.quantity}</td>
                    <td>{execution.price}</td>
                    <td>{execution.fee} {execution.fee_currency}</td>
                    <td>{formatDate(execution.executed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="history-empty"><Database size={18} /> No executions saved yet.</div>
        )}
      </section>

    </main>
  )
}

export default App
