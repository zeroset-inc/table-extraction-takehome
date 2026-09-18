use serde::{Deserialize, Serialize};

use crate::{Error, Result};

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TableOrientation {
    RecordsByRow,
    RecordsByColumn,
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceCoordinate {
    pub row: u32,
    pub column: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceRange {
    pub start: SourceCoordinate,
    pub end_exclusive: SourceCoordinate,
}

impl SourceRange {
    pub fn validate(self) -> Result<()> {
        if self.start.row >= self.end_exclusive.row
            || self.start.column >= self.end_exclusive.column
        {
            return Err(Error::invalid("source range must have positive area"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TableLayout {
    pub orientation: TableOrientation,
    /// Bounding rectangle containing header and data bands.
    pub source_range: SourceRange,
    pub header_ranges: Vec<SourceRange>,
    /// Ordered data rectangles. Gaps between them may contain repeated headers,
    /// notes, or separators and never consume a logical row.
    pub data_bands: Vec<TableDataBand>,
    pub label_columns: Vec<u32>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TableDataBand {
    pub logical_row_start: u64,
    pub source_range: SourceRange,
}

impl TableLayout {
    /// All declared header pieces before the first data record jointly define
    /// the schema. Later header pieces are exact source repetitions.
    pub fn primary_header_ranges(&self) -> Vec<SourceRange> {
        let Some(data) = self.data_bands.first() else {
            return vec![];
        };
        self.header_ranges
            .iter()
            .copied()
            .take_while(|r| match self.orientation {
                TableOrientation::RecordsByRow => {
                    r.end_exclusive.row <= data.source_range.start.row
                }
                TableOrientation::RecordsByColumn => {
                    r.end_exclusive.column <= data.source_range.start.column
                }
            })
            .collect()
    }

    pub fn validate(&self, row_count: u64, column_width: u32) -> Result<()> {
        self.source_range.validate()?;
        if row_count == 0
            || column_width == 0
            || self.header_ranges.len() > 64
            || self.data_bands.is_empty()
            || self.data_bands.len() > 4096
            || self.label_columns.len() > 64
        {
            return Err(Error::invalid("table layout exceeds its bounded metadata"));
        }
        for range in &self.header_ranges {
            range.validate()?;
            if !range_contains(self.source_range, *range) {
                return Err(Error::invalid(
                    "header range lies outside its source region",
                ));
            }
        }
        if self
            .header_ranges
            .windows(2)
            .any(|ranges| !range_precedes(ranges[0], ranges[1]))
        {
            return Err(Error::invalid(
                "header ranges must be ordered and non-overlapping",
            ));
        }
        if self.label_columns.windows(2).any(|pair| pair[0] >= pair[1]) {
            return Err(Error::invalid("label columns must be sorted and unique"));
        }
        if self
            .label_columns
            .last()
            .is_some_and(|column| *column >= column_width)
        {
            return Err(Error::invalid(
                "label column lies outside normalized schema",
            ));
        }
        let mut expected_logical_row = 0_u64;
        let mut previous_axis_end = None;
        for band in &self.data_bands {
            band.source_range.validate()?;
            if band.logical_row_start != expected_logical_row
                || !range_contains(self.source_range, band.source_range)
                || self
                    .header_ranges
                    .iter()
                    .any(|header| ranges_overlap(*header, band.source_range))
            {
                return Err(Error::invalid("invalid table data-band transform"));
            }
            let (rows, width, axis_start, axis_end) = match self.orientation {
                TableOrientation::RecordsByRow => (
                    u64::from(band.source_range.end_exclusive.row - band.source_range.start.row),
                    band.source_range.end_exclusive.column - band.source_range.start.column,
                    band.source_range.start.row,
                    band.source_range.end_exclusive.row,
                ),
                TableOrientation::RecordsByColumn => (
                    u64::from(
                        band.source_range.end_exclusive.column - band.source_range.start.column,
                    ),
                    band.source_range.end_exclusive.row - band.source_range.start.row,
                    band.source_range.start.column,
                    band.source_range.end_exclusive.column,
                ),
            };
            if width != column_width
                || previous_axis_end.is_some_and(|previous| axis_start < previous)
            {
                return Err(Error::invalid(
                    "table data bands must be ordered with exact schema width",
                ));
            }
            expected_logical_row = expected_logical_row
                .checked_add(rows)
                .ok_or_else(|| Error::invalid("table data-band row count overflow"))?;
            previous_axis_end = Some(axis_end);
        }
        if expected_logical_row != row_count {
            return Err(Error::invalid(
                "table data bands do not exactly cover normalized rows",
            ));
        }
        Ok(())
    }

    pub fn source_coordinate(
        &self,
        logical_row: u64,
        normalized_column: u32,
    ) -> Result<SourceCoordinate> {
        let band = self
            .data_bands
            .iter()
            .find(|band| {
                let rows = match self.orientation {
                    TableOrientation::RecordsByRow => {
                        band.source_range.end_exclusive.row - band.source_range.start.row
                    }
                    TableOrientation::RecordsByColumn => {
                        band.source_range.end_exclusive.column - band.source_range.start.column
                    }
                };
                logical_row >= band.logical_row_start
                    && band
                        .logical_row_start
                        .checked_add(u64::from(rows))
                        .is_some_and(|end| logical_row < end)
            })
            .ok_or_else(|| Error::invalid("logical row lies outside table data bands"))?;
        let row = u32::try_from(logical_row - band.logical_row_start)
            .map_err(|_| Error::invalid("logical row exceeds coordinate range"))?;
        let coordinate = match self.orientation {
            TableOrientation::RecordsByRow => SourceCoordinate {
                row: band
                    .source_range
                    .start
                    .row
                    .checked_add(row)
                    .ok_or_else(|| Error::invalid("source row overflow"))?,
                column: band
                    .source_range
                    .start
                    .column
                    .checked_add(normalized_column)
                    .ok_or_else(|| Error::invalid("source column overflow"))?,
            },
            TableOrientation::RecordsByColumn => SourceCoordinate {
                row: band
                    .source_range
                    .start
                    .row
                    .checked_add(normalized_column)
                    .ok_or_else(|| Error::invalid("source row overflow"))?,
                column: band
                    .source_range
                    .start
                    .column
                    .checked_add(row)
                    .ok_or_else(|| Error::invalid("source column overflow"))?,
            },
        };
        if coordinate.row >= band.source_range.end_exclusive.row
            || coordinate.column >= band.source_range.end_exclusive.column
        {
            return Err(Error::invalid(
                "logical cell lies outside the source region",
            ));
        }
        Ok(coordinate)
    }
}

fn range_contains(outer: SourceRange, inner: SourceRange) -> bool {
    inner.start.row >= outer.start.row
        && inner.end_exclusive.row <= outer.end_exclusive.row
        && inner.start.column >= outer.start.column
        && inner.end_exclusive.column <= outer.end_exclusive.column
}

fn ranges_overlap(left: SourceRange, right: SourceRange) -> bool {
    left.start.row < right.end_exclusive.row
        && right.start.row < left.end_exclusive.row
        && left.start.column < right.end_exclusive.column
        && right.start.column < left.end_exclusive.column
}

fn range_precedes(left: SourceRange, right: SourceRange) -> bool {
    !ranges_overlap(left, right)
        && (left.start.row, left.start.column) < (right.start.row, right.start.column)
}

