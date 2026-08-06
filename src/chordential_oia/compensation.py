"""What a writer is paid, and what they keep — one policy, stated once.

Before this, the number a composer was quoted came from wherever the conversation
happened. The estimate carried a `Composer` line of 20h × $150 = **$3,000 flat**, which
is 26.9% of an $11,133 :30 spot and **3.9% of a $76,191 orchestral anthem** — the same
money for what is plainly the harder brief. Nothing in the system said what a writer
should actually be paid, so the quote, the payout and the sentence said out loud to a
composer had no reason to agree.

**The fee is a share of NET CREATIVE REVENUE, not of price.** On that anthem, $32,125 of
the $76,191 is players and studio — money that passes through the studio to musicians and
a room. A share of gross would either overpay wildly or force a percentage so small it
insults people. Net is what the creative work is actually worth to the business.

Calibration, not invention: 30% of net on a :30 national spot is **$2,980** against the
$3,000 the estimator already modelled for that job. The policy and the price agree
because they were made to; the percentage then carries sensibly to jobs the flat line
priced absurdly.

**Publishing is split 50/50 with the writers, and the reason is timing.** Backend costs
the studio nothing today — there is no aired work, so the publisher's share is worth zero
this year — while cash is the scarce thing. Trading the free asset for the scarce one is
the correct trade for a studio with no catalogue, and it is a concrete, checkable promise
a composer can verify on the cue sheet rather than take on faith.

What this file will NOT do is put a writer's name in a publisher column without evidence
they can collect there (see `publisher_rows`). That is the ADR-0050 rule applied to
money: a share assigned to an entity that does not exist at a PRO is not generosity, it
is an unclaimed royalty and a wrong line on a filed legal document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

# Share of NET creative revenue paid to the writer(s) of a work.
COMPOSER_SHARE = 0.30
# When the writer also orchestrates or produces the recording session, they are doing
# two jobs and are paid for two.
COMPOSER_SHARE_WITH_SESSION = 0.40

# A submitted demo that does not win the job is still work. Industry practice runs
# $200-500 per submission; an unknown studio pays at the top of the range, because the
# thing being bought is a stranger's willingness to take it seriously.
DEMO_FEE = 400.0

# The publisher's half, split with the writers. 0.50 = even.
PUBLISHER_SPLIT_TO_WRITERS = 0.50

# The house's own publishing entity.
HOUSE_PUBLISHER = "Chordential Music"

# Who authors the work, and therefore shares the writer fee and the writer's share.
# Mirrors `delivery.WRITER_ROLES`: a mixer, an editor and a project manager are paid
# for their work and are not authors of it.
WRITER_ROLE_NAMES = frozenset({
    "composer", "co-composer", "arranger", "orchestrator", "topline", "topliner",
    "songwriter", "lyricist",
})


@dataclass
class WriterFee:
    """What one engagement pays, and how it was arrived at — so the number can be
    explained to the person receiving it without re-deriving it."""
    net_creative_revenue: float
    share: float
    total: float
    per_writer: float
    writers: int
    basis: str

    @property
    def explanation(self) -> str:
        return (f"{self.share:.0%} of ${self.net_creative_revenue:,.0f} net creative "
                f"revenue ({self.basis}) = ${self.total:,.0f}"
                + (f", split {self.writers} ways = ${self.per_writer:,.0f} each"
                   if self.writers > 1 else ""))


def net_creative_revenue(price: float, session_cost: float = 0.0) -> float:
    """Price less the money that passes through to players and the room.

    Session cost is not margin and never was: it is paid out to musicians and a studio.
    Including it in the base would mean a writer's fee rose because an orchestra was
    hired, which is not a fact about their work.
    """
    return max(0.0, float(price or 0.0) - float(session_cost or 0.0))


def writer_fee(price: float, session_cost: float = 0.0, *,
               writers: int = 1, orchestrates: bool = False,
               live_session: bool = False,
               share: Optional[float] = None) -> WriterFee:
    """The creative fee for a job, and each writer's cut of it.

    ``orchestrates`` is the uplift: the writer is doing a second job — scoring out the
    parts — whether those parts end up played by people or by samples. ``live_session``
    only changes what the fee is CALLED, and it exists because the first wiring of this
    told a composer they were being paid extra to "produce the session" on a sampled
    score that had no session. The rate was arguable; the reason was false, and a fee
    whose stated basis is untrue is worse than a lower one.
    """
    net = net_creative_revenue(price, session_cost)
    if share is None:
        share = COMPOSER_SHARE_WITH_SESSION if orchestrates else COMPOSER_SHARE
    total = net * share
    n = max(1, int(writers))
    if not orchestrates:
        basis = "writing and delivery"
    elif live_session:
        basis = "writer also orchestrates and produces the recording session"
    else:
        basis = "writer also orchestrates and produces the mock-up (no live session)"
    return WriterFee(
        net_creative_revenue=net, share=share, total=total,
        per_writer=total / n, writers=n, basis=basis,
    )


@dataclass
class PublisherRow:
    """One publisher on a cue sheet: who, what share, and whether we can prove it."""
    name: str
    share: float
    pro: str = ""
    #: True when this row exists only because a writer's own publishing entity is
    #: unknown — the house is holding the share, not keeping it.
    held_for: str = ""

    @property
    def share_label(self) -> str:
        return f"{self.share * 100:.0f}%"


def publisher_rows(writers: Sequence[dict],
                   *, split: float = PUBLISHER_SPLIT_TO_WRITERS) -> List[PublisherRow]:
    """The publisher side of a cue sheet under the 50/50 policy.

    A writer takes their part of the publisher's share **only when we know the
    publishing entity it would be paid to**. A composer who has never registered as a
    publisher with a PRO cannot collect on a publisher line, so writing their personal
    name there does not pay them — it creates an unclaimed share on a filed document and
    tells them, falsely, that they are covered.

    So an unknown entity leaves the share with the house, marked ``held_for`` that
    writer. That is a debt the console can show and chase, not a silent forfeit.

    ``writers`` are dicts with ``name`` and optionally ``publisher`` / ``pro``.
    """
    writers = [w for w in (writers or []) if (w or {}).get("name")]
    if not writers:
        return [PublisherRow(name=HOUSE_PUBLISHER, share=1.0)]

    to_writers = max(0.0, min(1.0, split))
    each = (to_writers / len(writers)) if writers else 0.0
    rows: List[PublisherRow] = []
    house = 1.0 - to_writers
    for w in writers:
        entity = (w.get("publisher") or "").strip()
        if entity:
            rows.append(PublisherRow(name=entity, share=each,
                                     pro=(w.get("pro") or "").strip()))
        else:
            # No entity to pay — the house holds it and the debt is named.
            house += each
            rows.append(PublisherRow(name=HOUSE_PUBLISHER, share=0.0,
                                     held_for=w["name"]))
    out = [PublisherRow(name=HOUSE_PUBLISHER, share=house)]
    out += [r for r in rows if r.share > 0 or r.held_for]
    return out


def unassigned_publishing(writers: Sequence[dict]) -> List[str]:
    """Writers whose half of publishing cannot be paid to them yet.

    Surfaced so the promise made when they were hired ("publishing 50/50") turns into a
    task — get their publishing entity and PRO — rather than quietly not happening.
    """
    return [w["name"] for w in (writers or [])
            if (w or {}).get("name") and not (w.get("publisher") or "").strip()]
