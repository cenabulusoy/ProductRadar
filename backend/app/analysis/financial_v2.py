"""Pure financial calculations. No I/O, system clock, scoring or legacy defaults."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext, ROUND_HALF_UP
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, BeforeValidator, field_validator, model_validator


def numeric(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a financial number")
    return value


Money = Annotated[Decimal, BeforeValidator(numeric), Field(ge=0, le=1000000000, decimal_places=4, allow_inf_nan=False)]
Price = Annotated[Decimal, BeforeValidator(numeric), Field(gt=0, le=1000000000, decimal_places=4, allow_inf_nan=False)]
Percent = Annotated[Decimal, BeforeValidator(numeric), Field(ge=0, le=100, decimal_places=4, allow_inf_nan=False)]
Basis = Literal["inclusive", "exclusive", "effective"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provenance(Model):
    kind: Literal["official_measured", "manual_or_imported", "derived", "estimated"]
    source: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    snapshot_id: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("recorded_at")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("Timestamp must include timezone")
        return value.astimezone(timezone.utc)

    @field_validator("source")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Source must not be blank")
        return value.strip()


class RateInput(Model):
    value: Percent | None = None
    provenance: Provenance


class SalePriceInput(Model):
    amount: Price | None = None
    vat_basis: Literal["inclusive", "exclusive"] | None = None
    provenance: Provenance


class CostInput(Model):
    amount: Money | None = None
    vat_basis: Basis | None = None
    vat_rate_percent: Percent | None = None
    input_vat_recoverable: bool | None = Field(default=None, strict=True)
    provenance: Provenance

    @model_validator(mode="after")
    def effective_has_no_tax_adjustment(self):
        if self.vat_basis == "effective" and (self.vat_rate_percent is not None or self.input_vat_recoverable is not None):
            raise ValueError("Effective costs already include all nonrecoverable taxes")
        return self


class CommissionInput(Model):
    fixed_fee: CostInput | None = None
    variable_rate_percent: Percent | None = None
    variable_fee_vat_basis: Basis | None = None
    variable_fee_vat_rate_percent: Percent | None = None
    variable_fee_input_vat_recoverable: bool | None = Field(default=None, strict=True)
    # A declaration of a flat tariff, or an explicit inclusive price range.
    flat_tariff_confirmed: bool | None = Field(default=None, strict=True)
    valid_from_gross_price: Money | None = None
    valid_to_gross_price: Price | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def consistent(self):
        if (self.valid_from_gross_price is None) != (self.valid_to_gross_price is None):
            raise ValueError("Commission price range requires both bounds")
        if self.valid_from_gross_price is not None and self.valid_to_gross_price <= self.valid_from_gross_price:
            raise ValueError("Invalid commission price range")
        if self.variable_fee_vat_basis == "effective" and (self.variable_fee_vat_rate_percent is not None or self.variable_fee_input_vat_recoverable is not None):
            raise ValueError("Effective variable fees cannot also specify VAT treatment")
        return self


class FinancialInputs(Model):
    currency: Literal["EUR"] = "EUR"
    scenario_mode: Literal["conservative", "manual"] = "conservative"
    planned_sale_price: SalePriceInput | None = None
    sales_vat_rate: RateInput | None = None
    landed_purchase_cost: CostInput | None = None
    fulfilment_cost: CostInput | None = None
    advertising_cost: CostInput | None = None
    returns_loss_reserve: CostInput | None = None
    other_allocated_cost: CostInput | None = None
    commission: CommissionInput | None = None


def rendered(value):
    return None if value is None else str(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def effective_cost(amount, basis, rate, recoverable):
    if amount is None or basis is None:
        return None
    if basis == "effective":
        return amount
    if rate is None or recoverable is None:
        return None
    factor = 1 + rate / 100
    if basis == "inclusive":
        return amount / factor if recoverable else amount
    return amount if recoverable else amount * factor


def market_reference(payload, snapshot_id, as_of):
    """Validate a saved observation independently of its cached derived summaries."""
    result = {"status": "unavailable", "reason": "missing_market_snapshot", "price": None,
              "snapshot_id": snapshot_id, "provenance": None, "offer_id": None}
    if payload is None:
        return result
    if not isinstance(payload, dict):
        result["reason"] = "invalid_market_snapshot"
        return result
    try:
        if (payload.get("status") != "complete" or payload.get("pagination_complete") is not True
                or payload.get("country") != "NL" or payload.get("condition") != "NEW"
                or payload.get("currency") != "EUR" or payload.get("api_version") != "v10"):
            result["reason"] = "market_incomplete_or_wrong_segment"
            return result
        measured = datetime.fromisoformat(payload["measured_at"])
        if measured.utcoffset() is None or measured > as_of:
            raise ValueError()
        result["provenance"] = {"kind": "official_measured", "source": "bol Retailer API v10 / products/{ean}/offers",
                                "recorded_at": measured.isoformat(), "snapshot_id": snapshot_id}
        if as_of - measured > timedelta(hours=24):
            result["reason"] = "market_older_than_24_hours"
            return result
        rows = payload["offers"]
        if not isinstance(rows, list):
            raise ValueError()
        if not rows:
            result["reason"] = "market_has_no_offers"
            return result
        offers = []
        seen = set()
        for row in rows:
            if (not isinstance(row, dict) or row.get("countryCode") != "NL" or row.get("condition") != "NEW"
                    or type(row.get("bestOffer")) is not bool or not isinstance(row.get("offerId"), str)
                    or not row["offerId"] or row["offerId"] in seen or isinstance(row.get("price"), bool)):
                raise ValueError()
            seen.add(row["offerId"])
            price = Decimal(str(row["price"]))
            if not price.is_finite() or price <= 0 or price > 1000000000 or price.as_tuple().exponent < -4:
                raise ValueError()
            offers.append((price, row["offerId"], row["bestOffer"]))
        best = [offer for offer in offers if offer[2]]
        chosen = min(best or offers, key=lambda item: (item[0], item[1]))
        result.update(status="usable", reason="lowest_bol_best_offer" if best else "lowest_offer_fallback",
                      price=rendered(chosen[0]), offer_id=chosen[1])
    except (ValueError, TypeError, KeyError, ArithmeticError):
        result.update(status="unavailable", reason="invalid_market_snapshot", price=None)
    return result


def calculate_financial(inputs: FinancialInputs, *, as_of: datetime, market_payload=None, snapshot_id=None):
    if as_of.utcoffset() is None:
        raise ValueError("as_of must include timezone")
    # Invalid future provenance must not be passed off as current evidence.
    def validate_dates(value):
        if isinstance(value, Provenance):
            if value.recorded_at > as_of:
                raise ValueError("Input provenance is in the future")
        elif isinstance(value, BaseModel):
            for name in type(value).model_fields:
                validate_dates(getattr(value, name))
    validate_dates(inputs)
    with localcontext() as context:
        context.prec = 40
        return _calculate(inputs, as_of, market_payload, snapshot_id)


def _calculate(inputs, as_of, market_payload, snapshot_id):
    rate = inputs.sales_vat_rate.value if inputs.sales_vat_rate else None
    planned = inputs.planned_sale_price
    gross = None
    if planned and planned.amount is not None:
        if planned.vat_basis == "inclusive":
            gross = planned.amount
        elif planned.vat_basis == "exclusive" and rate is not None:
            gross = planned.amount * (1 + rate / 100)
    reference = market_reference(market_payload, snapshot_id, as_of)
    chosen = None
    reason = "planned_price_or_vat_basis_missing"
    if gross is not None:
        if inputs.scenario_mode == "manual":
            chosen, reason = gross, "explicit_manual_scenario"
        elif reference["status"] == "usable":
            market_price = Decimal(reference["price"])
            chosen = min(gross, market_price)
            reason = "planned_price_not_above_market" if gross <= market_price else reference["reason"]
        else:
            reason = reference["reason"]
    cost_names = ("landed_purchase_cost", "fulfilment_cost", "advertising_cost", "returns_loss_reserve", "other_allocated_cost")
    normalized = {}
    for name in cost_names:
        cost = getattr(inputs, name)
        normalized[name] = None if cost is None else effective_cost(cost.amount, cost.vat_basis, cost.vat_rate_percent, cost.input_vat_recoverable)

    def scenario(price, stress=False):
        missing = []
        if price is None:
            missing.append("sale_price")
        if rate is None:
            missing.append("sales_vat_rate")
        revenue = price / (1 + rate / 100) if price is not None and rate is not None else None
        costs = {name: value * (Decimal("1.10") if stress and name != "landed_purchase_cost" else 1)
                 if value is not None else None for name, value in normalized.items()}
        missing.extend(name for name, value in costs.items() if value is None)
        commission = inputs.commission
        fixed = variable = fee = None
        if commission is not None and price is not None:
            in_range = (commission.valid_from_gross_price is not None
                        and commission.valid_from_gross_price <= price <= commission.valid_to_gross_price)
            applicable = in_range if commission.valid_from_gross_price is not None else commission.flat_tariff_confirmed is True
            if not applicable:
                missing.append("commission_tariff_not_confirmed_for_price")
            else:
                if commission.fixed_fee:
                    cost = commission.fixed_fee
                    fixed = effective_cost(cost.amount, cost.vat_basis, cost.vat_rate_percent, cost.input_vat_recoverable)
                if commission.variable_rate_percent is not None:
                    variable = effective_cost(price * commission.variable_rate_percent / 100,
                                              commission.variable_fee_vat_basis, commission.variable_fee_vat_rate_percent,
                                              commission.variable_fee_input_vat_recoverable)
                if fixed is not None and variable is not None:
                    fee = fixed + variable
        if fee is None:
            missing.append("commission")
        contribution = revenue - sum(costs.values()) - fee if revenue is not None and fee is not None and all(v is not None for v in costs.values()) else None
        margin = 100 * contribution / revenue if contribution is not None else None
        invested = costs["landed_purchase_cost"]
        roi = 100 * contribution / invested if contribution is not None and invested is not None and invested > 0 else None
        return {"status": "complete" if contribution is not None else "incomplete",
                "sale_price_including_vat": rendered(price), "revenue_excluding_vat": rendered(revenue),
                "sales_vat_amount": rendered(price - revenue) if price is not None and revenue is not None else None,
                "effective_costs": {name: rendered(value) for name, value in costs.items()},
                "commission_fixed": rendered(fixed), "commission_variable": rendered(variable), "commission_total": rendered(fee),
                "contribution_per_unit": rendered(contribution), "contribution_margin_percent": rendered(margin),
                "inventory_roi_percent": rendered(roi), "missing_inputs": missing,
                "roi_reason": "zero_landed_purchase_cost" if invested == 0 else ("incomplete_inputs" if roi is None else None)}

    return {"financial_engine_version": "2.0.0-financial.1", "input_schema_version": "1",
            "policy_version": "financial-nl-new-1", "as_of": as_of.isoformat(), "currency": "EUR",
            "label": "Bijdrage per stuk na opgenomen kosten",
            "input_provenance_status": "caller_declared; market_snapshot_server_loaded",
            "inputs": inputs.model_dump(mode="json"),
            "price_selection": {"mode": inputs.scenario_mode, "reason": reason,
                                "selected_from": ("planned_sale_price" if chosen == gross else "market_snapshot") if chosen is not None else None,
                                "selected_gross_price": rendered(chosen), "planned_gross_price": rendered(gross),
                                "market_reference": reference,
                                "provenance": {"kind": "derived", "source": "financial-nl-new-1 price selection",
                                               "recorded_at": as_of.isoformat(), "snapshot_id": snapshot_id,
                                               "depends_on": ["inputs.planned_sale_price", "inputs.sales_vat_rate", "price_selection.market_reference"]}},
            "manual": scenario(gross), "base": scenario(chosen),
            "stress": scenario(chosen * Decimal("0.90") if chosen is not None else None, stress=True),
            "calculation_provenance": {"kind": "derived", "source": "financial-engine/2.0.0-financial.1",
                                       "recorded_at": as_of.isoformat(), "snapshot_id": snapshot_id,
                                       "depends_on": ["inputs", "price_selection"],
                                       "stress_assumptions": {"sale_price_multiplier": "0.90", "operational_cost_multiplier": "1.10",
                                                              "landed_purchase_and_fixed_commission_unchanged": True}},
            "rounding": "Decimal precision 40; output 4 decimal places ROUND_HALF_UP; no intermediate rounding"}
