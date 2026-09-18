//! Geometric validation for spreadsheet table layouts.
//!
//! Lifted from the production ingestion service. The rules here decide whether a
//! proposed interpretation of a worksheet is *shaped* correctly: every occupied
//! cell classified exactly once, no overlaps, no blank records inside a data
//! band, headers at the region origin. They cannot decide whether the
//! interpretation is *meaningful* — that is the part this exercise is about.

mod compiler;
mod layout;
pub mod planner;

pub use compiler::{ModelLayoutProposal, RecordAxisInterval};
pub use layout::{SourceCoordinate, SourceRange, TableDataBand, TableLayout, TableOrientation};
pub use planner::{
    MAX_OOXML_HEADER_DEPTH, MAX_OOXML_LAYOUT_EVIDENCE_RANGES, MAX_OOXML_LAYOUT_HEADER_BANDS,
    MAX_OOXML_LAYOUT_REGIONS, MAX_OOXML_PRIMARY_HEADER_SPAN, OOXML_LAYOUT_PLANNER_CONTRACT,
    OoxmlLayoutDisposition, OoxmlLayoutEvidence, OoxmlLayoutExcludedRange,
    OoxmlLayoutPlannerDecision, OoxmlLayoutSelection, validate_ooxml_layout_planner_decision,
};

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Error {
    /// The proposal is malformed or contradicts the source geometry.
    Invalid(String),
    /// The proposal exceeds a declared bound.
    ResourceExhausted(String),
}

impl Error {
    pub fn invalid(message: impl Into<String>) -> Self {
        Self::Invalid(message.into())
    }

    pub fn resource_exhausted(message: impl Into<String>) -> Self {
        Self::ResourceExhausted(message.into())
    }

    pub fn backend(error: impl std::fmt::Display) -> Self {
        Self::Invalid(error.to_string())
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Invalid(message) => write!(f, "{message}"),
            Self::ResourceExhausted(message) => write!(f, "{message} (bound exceeded)"),
        }
    }
}

impl std::error::Error for Error {}
