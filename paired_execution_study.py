"""Frozen, causal BTC tape execution calibration; no book-depth claims.

Independent hypothetical cohorts share historical prints; they are alternatives,
not simultaneous claims on liquidity. Fees belong to the economics layer. The
study retains exact all-outcome denominators and conservative budget histograms,
with bounded deterministic samples of actual paths for expected-cost scenarios.
"""
from dataclasses import asdict, dataclass
import base64
import gzip
import hashlib
import heapq
import json
import math
import zlib

DAY_US = 86400_000000
YEAR_US = 365 * DAY_US
EPS = 1e-12
MAX_MODEL_JSON_BYTES = 64 * 1024 * 1024
BUDGET_EDGES = (0, .1, .25, .5, 1, 2, 3, 5, 7.5, 10, 15, 20, 30, 50, 75,
                100, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 10000)
MATURITY_DAYS = (1, 3, 7, 14, 30, 90, 365)
APPROXIMATION = ("Deterministic bounded samples of actual paths, stratified by completion status "
                 "and conservative budget bucket; exact stratum counts determine weights. "
                 "VWAP and quantity-weighted times summarize intrapath fills. Price quantiles "
                 "are approximate; all-outcome budget histogram counts are exact.")


def maturity_bucket(expiry_us, now_us):
    days = (expiry_us - now_us) / DAY_US
    if days <= 0:
        return None
    previous = 0
    for boundary in MATURITY_DAYS:
        if days <= boundary:
            return f"{previous}-{boundary}d"
        previous = boundary
    return "365d+"


@dataclass(frozen=True)
class StudyConfig:
    quantity_grid_btc: tuple = (.0001, .001, .01, .1)
    waiting_seconds: tuple = (.5, 1, 2, 5, 10, 30, 60)
    cohort_interval_seconds: float = 60
    max_quote_age_seconds: float = 60
    max_quote_skew_seconds: float = 1
    max_slice_btc: float = .01
    participation: float = 1
    observation_delay_seconds: float = 0
    decision_delay_seconds: float = 0
    order_delay_seconds: float = 0
    response_delay_seconds: float = 0
    spot_feed_delay_seconds: float = 0
    futures_feed_delay_seconds: float = 0
    half_spread_bps: float = 0
    slippage_bps: float = 0
    samples_per_stratum: int = 4
    maximum_contracts: int = 256

    def __post_init__(self):
        for name in ("quantity_grid_btc", "waiting_seconds"):
            values = tuple(float(x) for x in getattr(self, name))
            if not values or len(values) > 32 or any(not math.isfinite(x) or x <= 0 for x in values):
                raise ValueError(name + " requires 1 to 32 finite positive values")
            if tuple(sorted(set(values))) != values:
                raise ValueError(name + " must be strictly increasing")
            object.__setattr__(self, name, values)
        for name, value in asdict(self).items():
            if name in ("quantity_grid_btc", "waiting_seconds"):
                continue
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(name + " must be finite and nonnegative")
        if self.cohort_interval_seconds <= 0 or self.max_slice_btc <= 0 or not 0 < self.participation <= 1:
            raise ValueError("Positive interval/slice and participation in (0,1] required")
        if max(self.waiting_seconds) > 3600 or self.cohort_interval_seconds < 1:
            raise ValueError("Study windows are bounded to one hour and cohorts to at least one second")
        if not isinstance(self.samples_per_stratum, int) or not 1 <= self.samples_per_stratum <= 32:
            raise ValueError("samples_per_stratum must be an integer in [1,32]")
        if not isinstance(self.maximum_contracts, int) or not 1 <= self.maximum_contracts <= 256:
            raise ValueError("maximum_contracts must be an integer in [1,256]")
        if self.half_spread_bps + self.slippage_bps >= 10000:
            raise ValueError("Execution adjustments must leave a positive sell price")
        if self.max_quote_age_seconds > 86400 or any(getattr(self,name)>3600 for name in (
                "observation_delay_seconds","decision_delay_seconds","order_delay_seconds",
                "response_delay_seconds","spot_feed_delay_seconds","futures_feed_delay_seconds")):
            raise ValueError("Study quote age is bounded to one day and each delay to one hour")


def _weighted_quantiles(outcomes, field):
    pairs = sorted((o[field], o["weight"]) for o in outcomes
                   if o.get("completed") and o.get(field) is not None)
    total = math.fsum(weight for _, weight in pairs)
    result = {}
    for name, probability in (("p50", .5), ("p75", .75), ("p90", .9), ("p95", .95)):
        cumulative, found = 0.0, None
        for value, weight in pairs:
            cumulative += weight
            if cumulative + EPS >= total * probability:
                found = value
                break
        result[name] = found
    return result


def _budget_quantile(histogram, samples, confidence):
    rank = math.ceil(confidence * samples)
    cumulative = 0
    for index, count in enumerate(histogram[:-1]):
        cumulative += count
        if cumulative >= rank:
            return BUDGET_EDGES[index], cumulative / samples
    return None, cumulative / samples if samples else 0.0


class _Group:
    def __init__(self, metadata, sample_limit):
        self.metadata, self.sample_limit = metadata, sample_limit
        self.samples = self.completed = 0
        self.histogram = [0] * (len(BUDGET_EDGES) + 1)
        self.strata = {}

    def add(self, outcome):
        self.samples += 1
        self.completed += int(outcome["completed"])
        budget = outcome["max_adverse_budget_bps"]
        index = len(BUDGET_EDGES)
        if outcome["completed"] and budget is not None:
            index = next((i for i, edge in enumerate(BUDGET_EDGES) if edge + EPS >= budget), index)
        self.histogram[index] += 1
        key = (outcome["status"], index)
        state = self.strata.setdefault(key, {"count": 0, "samples": []})
        state["count"] += 1
        identity = (outcome["symbol"], outcome["decision_us"], outcome["requested_source_btc"], outcome["wait_seconds"])
        priority = int.from_bytes(hashlib.sha256(json.dumps(identity).encode()).digest()[:16], "big")
        item = (-priority, state["count"], outcome)
        heap = state["samples"]
        if len(heap) < self.sample_limit:
            heapq.heappush(heap, item)
        elif priority < -heap[0][0]:
            heapq.heapreplace(heap, item)

    def export(self):
        outcomes = []
        for key in sorted(self.strata):
            state = self.strata[key]
            weight = state["count"] / (self.samples * len(state["samples"]))
            outcomes.extend({**row, "weight": weight} for _, _, row in sorted(state["samples"]))
        return {**self.metadata, "samples": self.samples, "completed": self.completed,
                "completion_probability": self.completed / self.samples,
                "budget_histogram": self.histogram, "outcomes": outcomes,
                "joint_budget_quantiles_bps": {f"p{int(p*100)}": _budget_quantile(self.histogram, self.samples, p)[0]
                                               for p in (.5, .75, .9, .95)},
                "raw_basis_slip_quantiles_bps": _weighted_quantiles(outcomes, "raw_basis_slip_bps"),
                "annualized_slip_quantiles_bps": _weighted_quantiles(outcomes, "annualized_slip_bps")}


class FrozenExecutionModel:
    def __init__(self, data):
        if data.get("schema_version") != 1 or data.get("model_type") != "btc-tape-paired-execution-v1":
            raise ValueError("Unknown empirical execution model")
        if data["calibration_start_us"] >= data["label_cutoff_us"]:
            raise ValueError("Invalid calibration bounds")
        self.data = data
        self._groups = {(g["scope"], g.get("symbol") or g.get("maturity_bucket"), g.get("maturity_bucket"),
                         float(g["quantity_btc"]), float(g["wait_seconds"])): g for g in data["groups"]}

    @classmethod
    def from_dict(cls, data):
        if data.get("model_encoding") == "gzip-base64-v1":
            encoded = data.get("data", "")
            size = data.get("uncompressed_bytes")
            if (not isinstance(encoded, str) or len(encoded) > 4*((MAX_MODEL_JSON_BYTES+2)//3)
                    or not isinstance(size, int) or not 0 < size <= MAX_MODEL_JSON_BYTES):
                raise ValueError("Empirical model checkpoint exceeds bounded JSON size")
            try:
                packed = base64.b64decode(encoded, validate=True)
                decoder = zlib.decompressobj(31)
                raw = decoder.decompress(packed, MAX_MODEL_JSON_BYTES+1)
                if (len(raw) != size or len(raw) > MAX_MODEL_JSON_BYTES or not decoder.eof
                        or decoder.unused_data or decoder.unconsumed_tail):
                    raise ValueError("Invalid or oversized empirical model checkpoint")
                if hashlib.sha256(raw).hexdigest() != data.get("uncompressed_sha256"):
                    raise ValueError("Empirical model checkpoint checksum mismatch")
                data = json.loads(raw)
            except (ValueError, zlib.error, UnicodeDecodeError) as exc:
                raise ValueError("Invalid empirical model checkpoint: " + str(exc)) from exc
        return cls(data)

    def to_dict(self):
        return self.data

    def snapshot(self):
        """Compact JSON checkpoint; bounded gzip decoding, never executable data."""
        raw = json.dumps(self.data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > MAX_MODEL_JSON_BYTES:
            raise ValueError("Empirical model exceeds 64 MiB checkpoint JSON bound")
        return dict(model_encoding="gzip-base64-v1", uncompressed_bytes=len(raw),
                    uncompressed_sha256=hashlib.sha256(raw).hexdigest(),
                    data=base64.b64encode(gzip.compress(raw, compresslevel=6, mtime=0)).decode("ascii"))

    def forecast(self, symbol, expiry_us, now_us, quantity, wait_seconds, confidence=.95, min_samples=30):
        if not 0 < confidence <= 1 or not isinstance(min_samples, int) or min_samples < 1:
            raise ValueError("Confidence in (0,1] and positive integer minimum required")
        result = dict(available=False, requested_source_btc=quantity, wait_seconds=wait_seconds,
                      deadline_seconds=wait_seconds, samples=0, sample_count=0, confidence=confidence,
                      completion_probability=0.0, all_outcome_probability=0.0, budget_bps=None,
                      adverse_budget_bps=None, joint_success_probability=0.0, outcomes=[],
                      label_cutoff_us=self.data["label_cutoff_us"], scope=None,
                      scenario_approximation=APPROXIMATION, budget_clipped=False, execution_price_adjustments_included=True)
        if now_us < self.data["label_cutoff_us"]:
            return {**result, "reason": "calibration_labels_not_yet_available"}
        bucket = maturity_bucket(expiry_us, now_us)
        if bucket is None:
            return {**result, "reason": "expired_contract"}
        group = self._groups.get(("contract", symbol, bucket, float(quantity), float(wait_seconds)))
        scope = "contract"
        if group is None or group["samples"] < min_samples:
            scope = "maturity_bucket"
            group = self._groups.get((scope, bucket, bucket, float(quantity), float(wait_seconds)))
        if group is None:
            return {**result, "reason": "quantity_or_wait_not_calibrated", "scope": scope}
        result.update(samples=group["samples"], sample_count=group["samples"], scope=scope,
                      completion_probability=group["completion_probability"])
        result["metadata"] = dict(model_id=self.data["model_id"], calibration_end_us=self.data["calibration_end_us"],
            label_cutoff_us=self.data["label_cutoff_us"], sample_count=group["samples"], scope=scope,
            maturity_bucket=bucket, scenario_approximation=APPROXIMATION, budget_clipped=False,
            execution_price_adjustments_included=True)
        if group["samples"] < min_samples:
            return {**result, "reason": "insufficient_calibration_samples"}
        budget, joint = _budget_quantile(group["budget_histogram"], group["samples"], confidence)
        result.update(all_outcome_probability=joint, joint_success_probability=joint)
        if budget is None:
            return {**result, "reason": "joint_confidence_unattainable"}
        result.update(available=True, reason="calibrated_joint_completion_and_budget", budget_bps=budget,
                      adverse_budget_bps=budget, outcomes=group["outcomes"])
        return result


def select_execution_candidates(model, *, symbol, expiry_us, now_us, max_quantity_btc,
                                wait_seconds, confidence=.95, min_samples=30):
    model = model if isinstance(model, FrozenExecutionModel) else FrozenExecutionModel.from_dict(model)
    return [model.forecast(symbol, expiry_us, now_us, q, wait_seconds, confidence, min_samples)
            for q in model.data["config"]["quantity_grid_btc"] if q <= max_quantity_btc + EPS]


class _Episode:
    def __init__(self, symbol, expiry_us, now_us, quantity, spot, future, config):
        self.symbol, self.expiry_us, self.start, self.quantity = symbol, expiry_us, now_us, quantity
        self.spot, self.future, self.config = spot, future, config
        self.source = self.target = self.source_value = self.target_value = 0.0
        self.source_time = self.target_time = 0.0
        self.source_last = self.target_last = None
        self.source_adverse = self.target_adverse = 0.0
        self.phase = "source"
        self.eligible_us = now_us + round((config.decision_delay_seconds + config.order_delay_seconds) * 1e6)

    def trade(self, event):
        if (not event.executable or event.us <= self.eligible_us or event.us >= self.expiry_us
                or self.target >= self.quantity - EPS):
            return
        cfg = self.config
        expected_symbol = "SPOT" if self.phase == "source" else self.symbol
        expected_side = "sell" if self.phase == "source" else "buy"
        if event.symbol != expected_symbol or event.side != expected_side:
            return
        adjustment = (cfg.half_spread_bps + cfg.slippage_bps) / 10000
        ack = round(cfg.response_delay_seconds * 1e6)
        if self.phase == "source":
            quantity = min(event.btc * cfg.participation, self.quantity - self.source)
            if quantity <= EPS:
                return
            price = event.price * (1-adjustment)
            self.source += quantity
            self.source_value += quantity * price
            self.source_time += quantity * (event.us-self.start)/1e6
            self.source_last = event.us
            self.source_adverse = max(self.source_adverse, 10000*(1-price/self.spot.price))
            if self.source >= self.quantity - EPS:
                self.phase = "target"
                self.eligible_us = event.us + ack + round((cfg.decision_delay_seconds + cfg.order_delay_seconds)*1e6)
        else:
            quantity = min(event.btc * cfg.participation, self.quantity-self.target)
            if quantity <= EPS:
                return
            price = event.price * (1+adjustment)
            self.target += quantity
            self.target_value += quantity * price
            self.target_time += quantity * (event.us-self.start)/1e6
            self.target_last = event.us
            self.target_adverse = max(self.target_adverse, 10000*(price/self.future.price-1))
            if self.target >= self.quantity - EPS:
                self.phase = "done"

    def outcome(self, deadline, observations):
        source_ratio = self.source_value/self.source/self.spot.price if self.source > EPS else None
        target_ratio = self.target_value/self.target/self.future.price if self.target > EPS else None
        complete = self.target >= self.quantity - EPS
        status = "completed" if complete else ("unfilled" if self.source <= EPS else
                 "source_only" if self.target <= EPS else "partial")
        # Gross paired VWAP diagnostic: all filled quantities remain separately
        # visible; only completed paths enter the reported lease-slip quantiles.
        basis = (10000*(self.future.price/self.spot.price)*(target_ratio/source_ratio-1)
                 if source_ratio is not None and target_ratio is not None else None)
        years = (self.expiry_us-self.start)/YEAR_US
        current_spot, current_future = observations.get("SPOT"), observations.get(self.symbol)
        return dict(symbol=self.symbol, expiry_us=self.expiry_us, decision_us=self.start,
            source_observed_price=self.spot.price, target_observed_price=self.future.price,
            source_quote_us=self.spot.reported_us if self.spot.reported_us is not None else self.spot.us,
            target_quote_us=self.future.reported_us if self.future.reported_us is not None else self.future.us,
            source_available_us=self.spot.us+round((self.config.observation_delay_seconds+self.config.spot_feed_delay_seconds)*1e6),
            target_available_us=self.future.us+round((self.config.observation_delay_seconds+self.config.futures_feed_delay_seconds)*1e6),
            wait_seconds=(deadline-self.start)/1e6, requested_source_btc=self.quantity,
            source_fill_fraction=self.source/self.quantity, target_fill_fraction=self.target/self.quantity,
            source_vwap_ratio=source_ratio, target_vwap_ratio=target_ratio,
            source_vwap=self.source_value/self.source if self.source > EPS else None,
            target_vwap=self.target_value/self.target if self.target > EPS else None,
            source_completed_seconds=(self.source_last-self.start)/1e6 if self.source_last is not None else None,
            target_completed_seconds=(self.target_last-self.start)/1e6 if self.target_last is not None else None,
            source_fill_delay_seconds=self.source_time/self.source if self.source > EPS else None,
            target_fill_delay_seconds=self.target_time/self.target if self.target > EPS else None,
            worst_source_adverse_bps=self.source_adverse if self.source > EPS else None,
            worst_future_adverse_bps=self.target_adverse if self.target > EPS else None,
            max_adverse_budget_bps=max(self.source_adverse,self.target_adverse) if self.source > EPS else None,
            raw_basis_slip_bps=basis, annualized_slip_bps=basis/years if basis is not None and years > 0 else None,
            deadline_spot_ratio=current_spot.price/self.spot.price if current_spot else None,
            deadline_future_ratio=current_future.price/self.future.price if current_future else None,
            completed=complete, status=status, censored=not complete,
            censor_reason=None if complete else ("contract_expired" if deadline >= self.expiry_us else "waiting_deadline"),
            label_available_us=deadline+round(self.config.response_delay_seconds*1e6), budget_clipped=False,
            administratively_censored=False, completion_time_censored=not complete,
            execution_price_adjustments_included=True)


def runnerstudy(store, start_us, end_us, expiries, config=None, progress=None, sink=None):
    """Fit exactly the supplied historical window, without execution after cutoff.

    Caller supplies the reviewed ordered store and chooses a ten-day window
    strictly preceding evaluation. Short windows remain usable for unit tests.
    Simultaneous print ties retain store order. Fill windows are open at order
    arrival and close before the deadline print, matching exchange GTD. Cohort
    snapshots follow all same-timestamp prints. No full tape is retained.
    """
    cfg = config if isinstance(config, StudyConfig) else StudyConfig(**(config or {}))
    if not isinstance(start_us,int) or not isinstance(end_us,int) or start_us >= end_us:
        raise ValueError("Increasing integer microsecond study bounds required")
    if len(expiries) > cfg.maximum_contracts:
        raise ValueError("Study exceeds bounded contract count")
    active_bound = (math.ceil(max(cfg.waiting_seconds)/cfg.cohort_interval_seconds)+1)*len(cfg.quantity_grid_btc)*len(expiries)
    if active_bound > 16384:
        raise ValueError("Study grid would exceed 16,384 concurrent hypothetical cohorts")
    notify, emit = progress or (lambda *_: None), sink or (lambda row: None)
    observations, available_times, feeds, deadlines, active, groups = {}, {}, [], [], {}, {}
    executable_by_symbol = {}
    sequence = 0
    interval = round(cfg.cohort_interval_seconds*1e6)
    next_cohort = ((start_us+interval-1)//interval)*interval
    longest = round(max(cfg.waiting_seconds)*1e6)
    ack = round(cfg.response_delay_seconds*1e6)
    summary = dict(calibration_start_us=start_us, calibration_end_us=end_us, label_cutoff_us=end_us,
        cohorts_started=0, cohorts_excluded_at_cutoff=0, invalid_quote_opportunities=0, labels=0,
        completed_labels=0, partial_labels=0, unfilled_labels=0, market_events=0, maximum_active_cohorts=0,
        quantity_grid_btc=list(cfg.quantity_grid_btc), waiting_seconds=list(cfg.waiting_seconds),
        latency={k:v for k,v in asdict(cfg).items() if "delay_seconds" in k},
        scenario_approximation=APPROXIMATION, fees_included=False, budget_clipped=False,
        execution_price_adjustments_included=True)

    def drain_feeds(until):
        while feeds and feeds[0][0] <= until:
            available, _, event = heapq.heappop(feeds)
            previous = observations.get(event.symbol)
            old_source = previous.reported_us if previous and previous.reported_us is not None else (previous.us if previous else -1)
            source = event.reported_us if event.reported_us is not None else event.us
            if previous is None or (source,event.us) >= (old_source,previous.us):
                observations[event.symbol],available_times[event.symbol] = event,available

    def start_cohorts(now):
        nonlocal sequence
        spot = observations.get("SPOT")
        for symbol, expiry in sorted(expiries.items()):
            future = observations.get(symbol)
            if not spot or not future or not spot.executable or not future.executable or expiry <= now:
                summary["invalid_quote_opportunities"] += 1
                continue
            times = [x.reported_us if x.reported_us is not None else x.us for x in (spot,future)]
            if now-min(times) > cfg.max_quote_age_seconds*1e6 or abs(times[0]-times[1]) > cfg.max_quote_skew_seconds*1e6:
                summary["invalid_quote_opportunities"] += 1
                continue
            if now+longest+ack > end_us:
                summary["cohorts_excluded_at_cutoff"] += len(cfg.quantity_grid_btc)
                emit(dict(kind="cohort_excluded",decision_us=now,symbol=symbol,reason="label_window_crosses_cutoff"))
                continue
            for quantity in cfg.quantity_grid_btc:
                sequence += 1
                episode = _Episode(symbol,expiry,now,quantity,spot,future,cfg)
                active[sequence] = episode
                executable_by_symbol.setdefault("SPOT", {})[sequence] = episode
                for wait in cfg.waiting_seconds:
                    heapq.heappush(deadlines,(now+round(wait*1e6),sequence,wait))
                summary["cohorts_started"] += 1
        summary["maximum_active_cohorts"] = max(summary["maximum_active_cohorts"],len(active))

    def label(deadline, identifier, wait):
        episode = active[identifier]
        outcome = episode.outcome(deadline,observations)
        if outcome["label_available_us"] > end_us:
            raise AssertionError("A future label entered frozen calibration")
        for scope,identity in (("contract",episode.symbol),("maturity_bucket",maturity_bucket(episode.expiry_us,episode.start))):
            bucket = maturity_bucket(episode.expiry_us,episode.start)
            key = (scope,identity,bucket,episode.quantity,wait)
            if key not in groups:
                metadata = dict(scope=scope,maturity_bucket=bucket,quantity_btc=episode.quantity,wait_seconds=wait)
                metadata["symbol" if scope == "contract" else "maturity_bucket"] = identity
                groups[key] = _Group(metadata,cfg.samples_per_stratum)
            groups[key].add(outcome)
        summary["labels"] += 1
        summary["completed_labels" if outcome["completed"] else "unfilled_labels" if outcome["status"] == "unfilled" else "partial_labels"] += 1
        emit({"kind":"execution_outcome",**outcome})
        if wait == cfg.waiting_seconds[-1]:
            active.pop(identifier)
            executable_by_symbol.get("SPOT", {}).pop(identifier,None)
            executable_by_symbol.get(episode.symbol, {}).pop(identifier,None)

    def advance(until, inclusive):
        nonlocal next_cohort
        while True:
            pending = min(next_cohort if next_cohort < end_us else end_us+1,
                          feeds[0][0] if feeds else end_us+1,
                          deadlines[0][0] if deadlines else end_us+1)
            if pending > until or (pending == until and not inclusive):
                return
            drain_feeds(pending)
            if next_cohort == pending and pending < end_us:
                start_cohorts(pending)
                next_cohort += interval
            while deadlines and deadlines[0][0] <= pending:
                label(*heapq.heappop(deadlines))

    warmup = round((cfg.max_quote_age_seconds+cfg.observation_delay_seconds+
                    max(cfg.spot_feed_delay_seconds,cfg.futures_feed_delay_seconds))*1e6)
    previous_us = None
    for event in store.trades(start_us=start_us-warmup,end_us=end_us):
        if previous_us is not None and event.us < previous_us:
            raise ValueError("Study store must supply chronological effective events")
        if event.us >= end_us:
            raise ValueError("Store emitted data outside the frozen cutoff")
        if previous_us is not None and event.us != previous_us:
            advance(previous_us,True)
        advance(event.us,False)
        # GTD is half-open: deadline labels precede exchange prints at that
        # timestamp. Older feed arrivals at the deadline are already available.
        drain_feeds(event.us)
        while deadlines and deadlines[0][0] <= event.us:
            label(*heapq.heappop(deadlines))
        delay = cfg.observation_delay_seconds + (cfg.spot_feed_delay_seconds if event.symbol == "SPOT" else cfg.futures_feed_delay_seconds)
        sequence += 1
        heapq.heappush(feeds,(event.us+round(delay*1e6),sequence,event))
        if len(feeds) > 1_000_000:
            raise ValueError("Modeled feed delay exceeds the bounded observation queue")
        drain_feeds(event.us)
        # Same-timestamp cohorts are started by advance(previous_us, True) only
        # after all prints at that timestamp have updated the observations.
        for identifier,episode in tuple(executable_by_symbol.get(event.symbol, {}).items()):
            if event.us <= episode.start+longest:
                previous_phase = episode.phase
                episode.trade(event)
                if episode.phase != previous_phase:
                    executable_by_symbol[event.symbol].pop(identifier,None)
                    if episode.phase == "target":
                        executable_by_symbol.setdefault(episode.symbol,{})[identifier] = episode
        summary["market_events"] += 1
        if summary["market_events"] % 1_000_000 == 0:
            notify("execution_calibration",f"Scanned {summary['market_events']:,} prints; {summary['labels']:,} execution labels")
        previous_us = event.us
    advance(end_us,True)
    exported = [groups[key].export() for key in sorted(groups)]
    config_data = asdict(cfg)
    # Hash the complete frozen sufficient statistics and sampled scenarios.
    data = dict(schema_version=1,model_type="btc-tape-paired-execution-v1",calibration_start_us=start_us,
        calibration_end_us=end_us,label_cutoff_us=end_us,config=config_data,budget_edges_bps=list(BUDGET_EDGES),
        groups=exported,scenario_approximation=APPROXIMATION,fees_included=False,budget_clipped=False,
        execution_price_adjustments_included=True,
        execution_schedule="complete_source_tranche_then_same_btc_shadow_hedge",
        source_manifest_sha256=hashlib.sha256(getattr(store,"manifest_bytes",b"synthetic-fixture")).hexdigest(),
        ordering=getattr(store,"policy","caller_supplied_chronological"))
    data["model_id"] = hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False,separators=(",",":")).encode()).hexdigest()
    summary["model_id"] = data["model_id"]
    summary["group_summaries"] = [{k:v for k,v in group.items() if k not in ("outcomes","budget_histogram")}
                                  for group in exported if group["scope"] == "maturity_bucket"]
    notify("execution_calibration_complete",f"Frozen {summary['labels']:,} labels ending before evaluation")
    return {"model":data,"summary":summary}
