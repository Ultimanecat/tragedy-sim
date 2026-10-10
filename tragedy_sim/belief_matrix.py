"""Read-only, information-safe marginal projections shared by both AI sides.

Hard domains are conservative deductions. Empirical probabilities are labelled
and never turn a missed sample into a hard exclusion. Original witnesses remain
attached: a marginal table cannot encode every legal joint assignment.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import StrEnum
from math import isfinite
from typing import Any, Mapping, Sequence

from .catalog import MODULES, PLOTS
from .i18n import label
from .witness_types import PublicWitness, WitnessStrength


class HardStatus(StrEnum):
    ALWAYS = "always"
    NEVER = "never"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BeliefCell:
    hard_status: HardStatus
    approx_probability: float | None = None
    probability_source: str | None = None
    sample_count: float = 0
    sources: tuple[str, ...] = ()


class BeliefContradiction(ValueError):
    """A hard domain became empty; never recover by dropping evidence."""


@dataclass(frozen=True)
class AnyOf:
    # Each atom is (dimension, column, value); preserve the full witness too.
    atoms: tuple[tuple[str, str, str], ...]
    witness: PublicWitness


@dataclass(frozen=True)
class RoleCountBounds:
    minimum: int
    maximum: int


def _subject(cid: str) -> str:
    return "part_timer" if cid == "part_timer_question" else cid


def role_domains(view: Mapping[str, Any], witnesses: Sequence[PublicWitness]):
    """Initial-role outer bounds; no enumeration, RNG or hidden Game access."""
    module = str(view.get("module", ""))
    if module not in MODULES:
        raise ValueError(f"Unsupported belief module: {module}")
    roles = {"ordinary", *(role for plot in MODULES[module].plots for role in PLOTS[plot][2])}
    domains = {str(cid): set(roles) for cid in view.get("characters", ())
               if cid != "part_timer_question"}
    sources = {cid: [] for cid in domains}

    def restrict(cid, allowed, source):
        if cid in domains:
            domains[cid].intersection_update(allowed)
            sources[cid].append(source)
            if not domains[cid]:
                raise BeliefContradiction(f"Empty initial-role domain: {cid} ({source})")

    for cid, fact in view.get("known_roles", {}).items():
        if cid == "part_timer" or not isinstance(fact, Mapping):
            continue
        role = fact.get("role")
        if isinstance(role, str):
            allowed = {role}
            if module == "BTX" and role == "serial":
                allowed.add("ordinary")
            restrict(_subject(cid), allowed, "public_role_reveal")

    for witness in witnesses:
        if witness.strength != WitnessStrength.HARD:
            continue
        cid = _subject(witness.subject)
        if witness.kind == "role_is":
            allowed = {str(witness.value)}
            # Virus can temporarily turn an initial Ordinary into Serial.
            # Keep its plot condition in the original retained witness.
            if module == "BTX" and witness.value == "serial":
                allowed.add("ordinary")
            restrict(cid, allowed, witness.source)
        elif witness.kind == "role_in":
            restrict(cid, set(witness.value), witness.source)
        elif witness.kind == "role_not_in":
            restrict(cid, roles.difference(witness.value), witness.source)
    # Private answers are initial identities, more precise than current-role
    # public reveals. Only the supplied observer projection is consulted.
    for cid, role in view.get("protagonist_knowledge", {}).get("roles", {}).items():
        restrict(_subject(cid), {role}, "private_initial_role")
    return tuple(sorted(roles)), domains, sources


def _matrix(values, domains, sources, count_rows=(), *, column_key="character"):
    counts = {str(row[column_key]): row["counts"] for row in count_rows}
    result = {}
    for column, domain in domains.items():
        observed = counts.get(column, {})
        if any(not isinstance(count, (int, float)) or not isfinite(count) or count < 0
               for count in observed.values()):
            raise ValueError("Belief sample weights must be finite and non-negative")
        total = sum(observed.values())
        if any(count > 0 and value not in domain for value, count in observed.items()):
            raise BeliefContradiction(f"Sample outside hard domain: {column}")
        result[column] = {
            value: BeliefCell(
                HardStatus.NEVER if value not in domain else
                HardStatus.ALWAYS if len(domain) == 1 else HardStatus.UNKNOWN,
                observed.get(value, 0) / total if total else None,
                "empirical_samples" if total else None, total,
                tuple(dict.fromkeys(sources.get(column, ()))))
            for value in values}
    return result


@dataclass(frozen=True)
class BeliefMatrixProjection:
    module: str
    loop: int
    day: int
    roles: dict[str, dict[str, BeliefCell]]
    culprits: dict[str, dict[str, BeliefCell]]
    role_exists: dict[str, BeliefCell]
    role_count_bounds: dict[str, RoleCountBounds]
    any_of: tuple[AnyOf, ...]
    retained_witnesses: tuple[PublicWitness, ...]
    # Dark joint legality remains with the sampler; this slice retains its
    # sampled slot distribution, not a claim of a complete legal-card domain.
    dark_samples: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_view(cls, view: Mapping[str, Any], witnesses: Sequence[PublicWitness], *,
                  role_counts=(), culprit_counts=(), dark_counts=(),
                  role_assignments: Sequence[Mapping[str, str]] = ()):
        values, domains, sources = role_domains(view, witnesses)
        roles = _matrix(values, domains, sources, role_counts)
        culprit_domains = {str(item["day"]): set(domains)
                           for item in view.get("schedule", ())}
        culprit_sources = {day: [] for day in culprit_domains}
        for day, cid in view.get("known_culprits", {}).items():
            if str(day) in culprit_domains:
                culprit_domains[str(day)].intersection_update({_subject(cid)})
                culprit_sources[str(day)].append("public_culprit_reveal")
        for witness in witnesses:
            if witness.strength == WitnessStrength.HARD and witness.subject in culprit_domains:
                if witness.kind in {"culprit_is", "culprit_in"}:
                    allowed = ({witness.value} if witness.kind == "culprit_is" else set(witness.value))
                    culprit_domains[witness.subject].intersection_update(map(_subject, allowed))
                    culprit_sources[witness.subject].append(witness.source)
        for day, domain in culprit_domains.items():
            if not domain:
                raise BeliefContradiction(f"Empty culprit domain: {day}")
        culprits = _matrix(tuple(domains), culprit_domains, culprit_sources,
                           culprit_counts, column_key="day")
        disjunctions = []
        for witness in witnesses:
            atoms = ()
            if witness.kind == "role_pressure":
                atoms = tuple(("roles", _subject(cid), witness.subject)
                              for cid in witness.value.get("candidates", ()))
            elif witness.kind == "role_route_pressure":
                atoms = tuple(("roles", _subject(cid), role)
                              for role, candidates in witness.value.items() for cid in candidates)
            if atoms:
                disjunctions.append(AnyOf(atoms, deepcopy(witness)))
        exists, bounds = {}, {}
        for role in values:
            cells = [column[role] for column in roles.values()]
            always = sum(cell.hard_status == HardStatus.ALWAYS for cell in cells)
            possible = sum(cell.hard_status != HardStatus.NEVER for cell in cells)
            required_by_any_of = any(
                constraint.witness.strength == WitnessStrength.HARD
                and all(atom[0] == "roles" and atom[2] == role for atom in constraint.atoms)
                and all(atom[1] in roles for atom in constraint.atoms)
                for constraint in disjunctions)
            minimum = max(always, int(required_by_any_of))
            if minimum > possible:
                raise BeliefContradiction(f"Impossible existence constraint: {role}")
            bounds[role] = RoleCountBounds(minimum, possible)
            status = (HardStatus.ALWAYS if any(cell.hard_status == HardStatus.ALWAYS for cell in cells)
                      or required_by_any_of
                      else HardStatus.NEVER if all(cell.hard_status == HardStatus.NEVER for cell in cells)
                      else HardStatus.UNKNOWN)
            probability = (sum(any(assignment.get(cid) == role for cid in domains)
                               for assignment in role_assignments) / len(role_assignments)
                           if role_assignments else None)
            exists[role] = BeliefCell(status, probability,
                                     "empirical_joint_assignments" if role_assignments else None,
                                     len(role_assignments))
        return cls(str(view["module"]), int(view.get("loop", 1)), int(view.get("round", 1)),
                   roles, culprits, exists, bounds, tuple(disjunctions),
                   tuple(deepcopy(witnesses)), tuple(deepcopy(dark_counts)))

    def to_dict(self):
        return asdict(self)

    def to_text(self):
        lines = [f"信念矩阵：{self.module} 第{self.loop}轮第{self.day}天（概率为近似采样）"]
        for dimension, columns in (("身份", self.roles), ("当事人", self.culprits)):
            for column, cells in columns.items():
                content = "; ".join(f"{label('roles' if dimension == '身份' else 'characters', value)}={cell.hard_status}"
                                    + (f"/{cell.approx_probability:.1%}" if cell.approx_probability is not None else "")
                                    for value, cell in cells.items())
                lines.append(f"{dimension} {label('characters', column) if dimension == '身份' else '第' + column + '天'}: {content}")
        for constraint in self.any_of:
            lines.append(f"析取 {constraint.witness.strength}: {constraint.atoms} ({constraint.witness.source})")
        lines.append(f"保留原始 witness {len(self.retained_witnesses)} 条；未投影关系仍须 matcher 检查。")
        return "\n".join(lines)
