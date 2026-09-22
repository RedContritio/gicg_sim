use serde::Serialize;
use strum::Display;

use crate::Element;

pub(crate) const FROZEN: &str = "system.frozen";
pub(crate) const CRYSTALLIZE_SHIELD: &str = "system.crystallize_shield";
pub(crate) const BURNING_FLAME: &str = "system.burning_flame";
pub(crate) const DENDRO_CORE: &str = "system.dendro_core";
pub(crate) const CATALYZING_FIELD: &str = "system.catalyzing_field";

#[derive(Clone, Copy, Debug, Display, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
#[strum(serialize_all = "snake_case")]
pub enum Reaction {
    Vaporize,
    Melt,
    Overloaded,
    Superconduct,
    ElectroCharged,
    Frozen,
    Swirl,
    Crystallize,
    Burning,
    Bloom,
    Quicken,
    Shatter,
}

#[derive(Clone, Copy)]
pub(crate) struct ReactionMatch {
    pub kind: Reaction,
    pub aura: Element,
}

const PAIRS: &[(Element, Element, Reaction)] = &[
    (Element::Pyro, Element::Hydro, Reaction::Vaporize),
    (Element::Pyro, Element::Cryo, Reaction::Melt),
    (Element::Pyro, Element::Electro, Reaction::Overloaded),
    (Element::Pyro, Element::Dendro, Reaction::Burning),
    (Element::Cryo, Element::Electro, Reaction::Superconduct),
    (Element::Cryo, Element::Hydro, Reaction::Frozen),
    (Element::Hydro, Element::Electro, Reaction::ElectroCharged),
    (Element::Hydro, Element::Dendro, Reaction::Bloom),
    (Element::Electro, Element::Dendro, Reaction::Quicken),
];

pub(crate) fn resolve(auras: &[Element], incoming: Element) -> Option<ReactionMatch> {
    auras.iter().find_map(|aura| {
        reaction_for(*aura, incoming).map(|kind| ReactionMatch { kind, aura: *aura })
    })
}

fn reaction_for(aura: Element, incoming: Element) -> Option<Reaction> {
    if incoming == Element::Anemo && aura.can_swirl() {
        return Some(Reaction::Swirl);
    }
    if incoming == Element::Geo && aura.can_swirl() {
        return Some(Reaction::Crystallize);
    }
    PAIRS
        .iter()
        .find(|(left, right, _)| pair_matches(*left, *right, aura, incoming))
        .map(|(_, _, reaction)| *reaction)
}

fn pair_matches(left: Element, right: Element, aura: Element, incoming: Element) -> bool {
    (left == aura && right == incoming) || (left == incoming && right == aura)
}

impl Reaction {
    pub(crate) const fn bonus(self) -> i32 {
        match self {
            Self::Vaporize | Self::Melt | Self::Overloaded | Self::Shatter => 2,
            Self::Superconduct
            | Self::ElectroCharged
            | Self::Frozen
            | Self::Crystallize
            | Self::Burning
            | Self::Bloom
            | Self::Quicken => 1,
            Self::Swirl => 0,
        }
    }

    pub(crate) const fn collateral(self, aura: Element) -> Option<Element> {
        match self {
            Self::Superconduct | Self::ElectroCharged => Some(Element::Piercing),
            Self::Swirl => Some(aura),
            _ => None,
        }
    }

    pub(crate) const fn modifier(self) -> Option<&'static str> {
        match self {
            Self::Frozen => Some(FROZEN),
            Self::Crystallize => Some(CRYSTALLIZE_SHIELD),
            Self::Burning => Some(BURNING_FLAME),
            Self::Bloom => Some(DENDRO_CORE),
            Self::Quicken => Some(CATALYZING_FIELD),
            _ => None,
        }
    }

    pub(crate) const fn force_switch(self) -> bool {
        matches!(self, Self::Overloaded)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_element_pairs_resolve() {
        for (left, right, expected) in PAIRS {
            assert_eq!(resolve(&[*left], *right).unwrap().kind, *expected);
            assert_eq!(resolve(&[*right], *left).unwrap().kind, *expected);
        }
        assert_eq!(
            resolve(&[Element::Pyro], Element::Anemo).unwrap().kind,
            Reaction::Swirl
        );
        assert_eq!(
            resolve(&[Element::Hydro], Element::Geo).unwrap().kind,
            Reaction::Crystallize
        );
        assert!(resolve(&[Element::Dendro], Element::Anemo).is_none());
    }
}
