//! Expands a model proposal into durable geometry.
//!
//! The model answers with intervals on the *record axis* only: absolute source
//! rows for `records_by_row`, absolute columns for `records_by_column`. This
//! module stamps each interval across the region's full field width and assigns
//! logical row offsets. It expands and bounds; it never repairs a choice.

use serde::{Deserialize, Serialize};

use crate::{
    Error, OoxmlLayoutExcludedRange, OoxmlLayoutPlannerDecision, OoxmlLayoutSelection, Result,
    SourceRange, TableDataBand, TableLayout, TableOrientation, planner,
};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelLayoutProposal {
    pub contract: String,
    pub selections: Vec<ModelLayoutRegion>,
    #[serde(default)]
    pub excluded_ranges: Vec<OoxmlLayoutExcludedRange>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelLayoutRegion {
    pub region_id: String,
    pub orientation: TableOrientation,
    pub source_range: SourceRange,
    pub header_bands: Vec<RecordAxisInterval>,
    pub data_bands: Vec<RecordAxisInterval>,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecordAxisInterval {
    pub start: u32,
    pub end_exclusive: u32,
}

impl RecordAxisInterval {
    fn source_range(&self, mut bounds: SourceRange, orientation: TableOrientation) -> SourceRange {
        match orientation {
            TableOrientation::RecordsByRow => {
                bounds.start.row = self.start;
                bounds.end_exclusive.row = self.end_exclusive;
            }
            TableOrientation::RecordsByColumn => {
                bounds.start.column = self.start;
                bounds.end_exclusive.column = self.end_exclusive;
            }
        }
        bounds
    }
}

impl ModelLayoutProposal {
    pub fn into_decision(self) -> Result<OoxmlLayoutPlannerDecision> {
        // Bound expansion before allocating the durable geometry. The validator
        // still owns ordering, depth, disjointness and source coverage.
        if self.selections.len() > planner::MAX_OOXML_LAYOUT_REGIONS
            || self.excluded_ranges.len() > planner::MAX_OOXML_LAYOUT_EVIDENCE_RANGES
            || self.selections.iter().any(|region| {
                region.header_bands.len() > planner::MAX_OOXML_LAYOUT_HEADER_BANDS
                    || region.data_bands.len() > planner::MAX_OOXML_LAYOUT_EVIDENCE_RANGES
            })
        {
            return Err(Error::invalid(
                "table layout proposal exceeds its inventory bound",
            ));
        }
        let classifications = self.excluded_ranges.len()
            + self
                .selections
                .iter()
                .map(|region| region.header_bands.len() + region.data_bands.len())
                .sum::<usize>();
        if classifications > planner::MAX_OOXML_LAYOUT_EVIDENCE_RANGES {
            return Err(Error::invalid(
                "table layout classifications exceed their bound",
            ));
        }
        let selections = self
            .selections
            .into_iter()
            .map(|region| {
                let header_ranges = region
                    .header_bands
                    .iter()
                    .map(|interval| interval.source_range(region.source_range, region.orientation))
                    .collect();
                let mut logical_row_start = 0_u64;
                let data_bands = region
                    .data_bands
                    .iter()
                    .map(|interval| {
                        let records = interval
                            .end_exclusive
                            .checked_sub(interval.start)
                            .filter(|length| *length > 0)
                            .ok_or_else(|| {
                                Error::invalid("table layout interval must be positive")
                            })?;
                        let band = TableDataBand {
                            logical_row_start,
                            source_range: interval
                                .source_range(region.source_range, region.orientation),
                        };
                        logical_row_start += u64::from(records);
                        Ok(band)
                    })
                    .collect::<Result<Vec<_>>>()?;
                Ok(OoxmlLayoutSelection {
                    region_id: region.region_id,
                    layout: TableLayout {
                        orientation: region.orientation,
                        source_range: region.source_range,
                        header_ranges,
                        data_bands,
                        label_columns: vec![],
                    },
                })
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(OoxmlLayoutPlannerDecision {
            contract: self.contract,
            selections,
            excluded_ranges: self.excluded_ranges,
        })
    }
}
