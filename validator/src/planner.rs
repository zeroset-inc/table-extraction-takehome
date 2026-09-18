use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

use crate::{Error, Result, SourceRange, TableDataBand, TableLayout, TableOrientation};

pub const OOXML_LAYOUT_PLANNER_CONTRACT: &str = "table.layout-proposal.v1";
pub const MAX_OOXML_HEADER_DEPTH: u32 = 8;
pub const MAX_OOXML_PRIMARY_HEADER_SPAN: u32 = 16;
pub const MAX_OOXML_LAYOUT_HEADER_BANDS: usize = 32;
pub const MAX_OOXML_LAYOUT_ALTERNATIVES: usize =
    MAX_TABLE_ARTIFACTS_PER_SOURCE_GENERATION * 2 * MAX_OOXML_HEADER_DEPTH as usize;
pub const MAX_OOXML_LAYOUT_DECISION_SHEETS: usize =
    MAX_TABLE_ARTIFACTS_PER_SOURCE_GENERATION;
pub const MAX_OOXML_LAYOUT_SAMPLES_PER_SHEET: usize = 32;
pub const MAX_OOXML_LAYOUT_VALUE_SHAPE_BYTES: usize = 64;
pub const MAX_OOXML_LAYOUT_DECISION_SET_BYTES: usize = 128 * 1024;

/// One worksheet-wide evidence window; geometry is exact, samples are bounded.
/// A single window permits global split/merge reconciliation without duplicate calls.
pub const MAX_OOXML_LAYOUT_EVIDENCE_RANGES: usize = 1024;
pub const MAX_OOXML_LAYOUT_REQUEST_BYTES: usize = 128 * 1024;
pub const MAX_TABLE_ARTIFACTS_PER_SOURCE_GENERATION: usize = 64;
pub const MAX_OOXML_LAYOUT_REGIONS: usize = MAX_TABLE_ARTIFACTS_PER_SOURCE_GENERATION;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OoxmlLayoutStyle {
    pub bold: bool,
    /// Workbook-local fill equivalence class, never raw color or style XML.
    pub fill: u32,
    /// Top, right, bottom and left visible border edges, respectively.
    pub borders: u8,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OoxmlLayoutEvidence {
    pub window: SourceRange,
    pub occupied_ranges: Vec<SourceRange>,
    pub merged_ranges: Vec<SourceRange>,
    pub explicit_table_ranges: Vec<SourceRange>,
}

impl OoxmlLayoutEvidence {
    pub fn validate(&self) -> Result<()> {
        self.window.validate()?;
        if self.occupied_ranges.is_empty()
            || self.occupied_ranges.len()
                + self.merged_ranges.len()
                + self.explicit_table_ranges.len()
                > MAX_OOXML_LAYOUT_EVIDENCE_RANGES
        {
            return Err(Error::resource_exhausted(
                "OOXML evidence inventory exceeds its bound",
            ));
        }
        for range in self
            .occupied_ranges
            .iter()
            .chain(&self.merged_ranges)
            .chain(&self.explicit_table_ranges)
        {
            range.validate()?;
            if !range_contains(self.window, *range) {
                return Err(Error::invalid(
                    "OOXML evidence exceeds its worksheet window",
                ));
            }
        }
        validate_disjoint(&self.occupied_ranges)?;
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OoxmlLayoutAlternative {
    pub region_id: String,
    pub source_range: SourceRange,
    pub orientation: TableOrientation,
    pub header_depth: u32,
    pub deterministic_score: i32,
}

impl OoxmlLayoutAlternative {
    pub fn validate(&self) -> Result<()> {
        self.source_range.validate()?;
        if self.region_id.trim().is_empty()
            || self.region_id.len() > 256
            || !(1..=MAX_OOXML_HEADER_DEPTH).contains(&self.header_depth)
        {
            return Err(Error::invalid("invalid OOXML layout alternative"));
        }
        let record_axis_length = match self.orientation {
            TableOrientation::RecordsByRow => {
                self.source_range.end_exclusive.row - self.source_range.start.row
            }
            TableOrientation::RecordsByColumn => {
                self.source_range.end_exclusive.column - self.source_range.start.column
            }
        };
        if self.header_depth >= record_axis_length {
            return Err(Error::invalid(
                "OOXML layout header must leave at least one record",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OoxmlLayoutSelection {
    pub region_id: String,
    pub layout: TableLayout,
}

impl OoxmlLayoutSelection {
    pub fn from_alternative(alternative: &OoxmlLayoutAlternative) -> Self {
        let mut header = alternative.source_range;
        let mut data = alternative.source_range;
        match alternative.orientation {
            TableOrientation::RecordsByRow => {
                header.end_exclusive.row = header.start.row + alternative.header_depth;
                data.start.row = header.end_exclusive.row;
            }
            TableOrientation::RecordsByColumn => {
                header.end_exclusive.column = header.start.column + alternative.header_depth;
                data.start.column = header.end_exclusive.column;
            }
        }
        Self {
            region_id: alternative.region_id.clone(),
            layout: TableLayout {
                orientation: alternative.orientation,
                source_range: alternative.source_range,
                header_ranges: vec![header],
                data_bands: vec![TableDataBand {
                    logical_row_start: 0,
                    source_range: data,
                }],
                label_columns: vec![],
            },
        }
    }

    pub fn header_depth(&self) -> Result<u32> {
        Ok(self
            .layout
            .primary_header_ranges()
            .iter()
            .map(|r| match self.layout.orientation {
                TableOrientation::RecordsByRow => r.end_exclusive.row - r.start.row,
                TableOrientation::RecordsByColumn => r.end_exclusive.column - r.start.column,
            })
            .sum())
    }

    pub fn validate(&self) -> Result<()> {
        let layout = &self.layout;
        layout.source_range.validate()?;
        if self.region_id.is_empty()
            || self.region_id.len() > 256
            || !self
                .region_id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
            || !layout.label_columns.is_empty()
            || layout.header_ranges.is_empty()
            || layout.header_ranges.len() > MAX_OOXML_LAYOUT_HEADER_BANDS
            || layout.data_bands.is_empty()
            || layout.data_bands.len() > MAX_OOXML_LAYOUT_EVIDENCE_RANGES
        {
            return Err(Error::invalid("invalid layout proposal"));
        }
        let mut rows = 0_u64;
        for band in &layout.data_bands {
            band.source_range.validate()?;
            rows += match layout.orientation {
                TableOrientation::RecordsByRow => {
                    u64::from(band.source_range.end_exclusive.row - band.source_range.start.row)
                }
                TableOrientation::RecordsByColumn => u64::from(
                    band.source_range.end_exclusive.column - band.source_range.start.column,
                ),
            };
        }
        let width = match layout.orientation {
            TableOrientation::RecordsByRow => {
                layout.source_range.end_exclusive.column - layout.source_range.start.column
            }
            TableOrientation::RecordsByColumn => {
                layout.source_range.end_exclusive.row - layout.source_range.start.row
            }
        };
        layout.validate(rows, width)?;
        if layout.header_ranges[0].start != layout.source_range.start {
            return Err(Error::invalid(
                "primary header must start at the table origin",
            ));
        }
        let primary = layout.primary_header_ranges();
        let span = primary
            .last()
            .map(|r| match layout.orientation {
                TableOrientation::RecordsByRow => {
                    r.end_exclusive.row - layout.source_range.start.row
                }
                TableOrientation::RecordsByColumn => {
                    r.end_exclusive.column - layout.source_range.start.column
                }
            })
            .unwrap_or(0);
        if !(1..=MAX_OOXML_HEADER_DEPTH).contains(&self.header_depth()?)
            || span > MAX_OOXML_PRIMARY_HEADER_SPAN
        {
            return Err(Error::invalid(
                "primary header exceeds level or span bounds",
            ));
        }
        for (index, header) in layout.header_ranges.iter().enumerate() {
            let (depth, full_width) = match layout.orientation {
                TableOrientation::RecordsByRow => (
                    header.end_exclusive.row - header.start.row,
                    header.start.column == layout.source_range.start.column
                        && header.end_exclusive.column == layout.source_range.end_exclusive.column,
                ),
                TableOrientation::RecordsByColumn => (
                    header.end_exclusive.column - header.start.column,
                    header.start.row == layout.source_range.start.row
                        && header.end_exclusive.row == layout.source_range.end_exclusive.row,
                ),
            };
            if !(1..=MAX_OOXML_HEADER_DEPTH).contains(&depth)
                || !full_width
                || (index >= primary.len() && depth != 1)
            {
                return Err(Error::invalid("proposal header violates normalizer bounds"));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OoxmlLayoutDisposition {
    NonTable,
    Unresolved,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OoxmlLayoutExcludedRange {
    pub source_range: SourceRange,
    pub disposition: OoxmlLayoutDisposition,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OoxmlLayoutPlannerDecision {
    pub contract: String,
    pub selections: Vec<OoxmlLayoutSelection>,
    pub excluded_ranges: Vec<OoxmlLayoutExcludedRange>,
}

impl OoxmlLayoutPlannerDecision {
    pub fn validate(&self) -> Result<()> {
        if self.contract != OOXML_LAYOUT_PLANNER_CONTRACT
            || self.selections.len() > MAX_OOXML_LAYOUT_REGIONS
            || self.excluded_ranges.len() > MAX_OOXML_LAYOUT_EVIDENCE_RANGES
            || (self.selections.is_empty() && self.excluded_ranges.is_empty())
        {
            return Err(Error::invalid(
                "invalid layout decision contract or inventory",
            ));
        }
        let mut ids = BTreeSet::new();
        for selection in &self.selections {
            selection.validate()?;
            if !ids.insert(&selection.region_id) {
                return Err(Error::invalid("duplicate layout region ID"));
            }
        }
        validate_disjoint(
            &self
                .selections
                .iter()
                .map(|s| s.layout.source_range)
                .collect::<Vec<_>>(),
        )?;
        for excluded in &self.excluded_ranges {
            excluded.source_range.validate()?;
        }
        let classified = self.classified_ranges();
        if classified.len() > MAX_OOXML_LAYOUT_EVIDENCE_RANGES {
            return Err(Error::resource_exhausted(
                "layout classifications exceed their bound",
            ));
        }
        validate_disjoint(&classified)?;
        Ok(())
    }

    fn classified_ranges(&self) -> Vec<SourceRange> {
        self.selections
            .iter()
            .flat_map(|selection| {
                selection.layout.header_ranges.iter().copied().chain(
                    selection
                        .layout
                        .data_bands
                        .iter()
                        .map(|band| band.source_range),
                )
            })
            .chain(self.excluded_ranges.iter().map(|range| range.source_range))
            .collect()
    }
}

pub fn validate_ooxml_layout_planner_decision(
    evidence: &OoxmlLayoutEvidence,
    decision: &OoxmlLayoutPlannerDecision,
) -> Result<()> {
    evidence.validate()?;
    decision.validate()?;
    let classified = decision.classified_ranges();
    for range in classified
        .iter()
        .chain(decision.selections.iter().map(|s| &s.layout.source_range))
    {
        if !range_contains(evidence.window, *range) {
            return Err(Error::invalid("layout proposal exceeds admitted evidence"));
        }
    }
    // Disjoint classifications must cover every occupied cell, including detector misses.
    // Rectangle intersection areas avoid enumerating a potentially huge worksheet.
    for occupied in &evidence.occupied_ranges {
        let covered: u64 = classified
            .iter()
            .map(|range| intersection_area(*occupied, *range))
            .sum();
        if covered != intersection_area(*occupied, *occupied) {
            return Err(Error::invalid(
                "layout proposal leaves occupied source cells unaccounted for",
            ));
        }
    }
    for selection in &decision.selections {
        for band in &selection.layout.data_bands {
            validate_populated_records(
                &evidence.occupied_ranges,
                band.source_range,
                selection.layout.orientation,
            )?;
        }
        for range in selection.layout.header_ranges.iter().chain(
            selection
                .layout
                .data_bands
                .iter()
                .map(|band| &band.source_range),
        ) {
            if !evidence
                .occupied_ranges
                .iter()
                .any(|occupied| intersection_area(*range, *occupied) > 0)
            {
                return Err(Error::invalid(
                    "layout proposal selects an empty header or data band",
                ));
            }
        }
    }
    Ok(())
}

fn validate_populated_records(
    occupied: &[SourceRange],
    band: SourceRange,
    orientation: TableOrientation,
) -> Result<()> {
    let axis = |range: SourceRange| match orientation {
        TableOrientation::RecordsByRow => (range.start.row, range.end_exclusive.row),
        TableOrientation::RecordsByColumn => (range.start.column, range.end_exclusive.column),
    };
    let (mut cursor, end) = axis(band);
    let mut intervals = occupied
        .iter()
        .filter(|range| intersection_area(**range, band) > 0)
        .map(|range| axis(*range))
        .collect::<Vec<_>>();
    intervals.sort_unstable();
    for (start, next) in intervals {
        if start > cursor {
            break;
        }
        cursor = cursor.max(next);
        if cursor >= end {
            return Ok(());
        }
    }
    Err(Error::invalid(
        "layout data band contains empty source records; split around blank gaps",
    ))
}

fn range_contains(outer: SourceRange, inner: SourceRange) -> bool {
    inner.start.row >= outer.start.row
        && inner.start.column >= outer.start.column
        && inner.end_exclusive.row <= outer.end_exclusive.row
        && inner.end_exclusive.column <= outer.end_exclusive.column
}

fn intersection_area(a: SourceRange, b: SourceRange) -> u64 {
    u64::from(
        a.end_exclusive
            .row
            .min(b.end_exclusive.row)
            .saturating_sub(a.start.row.max(b.start.row)),
    ) * u64::from(
        a.end_exclusive
            .column
            .min(b.end_exclusive.column)
            .saturating_sub(a.start.column.max(b.start.column)),
    )
}

fn validate_disjoint(ranges: &[SourceRange]) -> Result<()> {
    for (index, range) in ranges.iter().enumerate() {
        if ranges[..index]
            .iter()
            .any(|other| intersection_area(*range, *other) > 0)
        {
            return Err(Error::invalid("overlapping layout source ranges"));
        }
    }
    Ok(())
}
