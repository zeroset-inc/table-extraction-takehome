//! The rules a proposal has to satisfy, as executable examples.
//!
//! Each test states one rule and the error a violation produces. Run with
//! `cargo test`. The fixtures mirror `cases/above_below`: a five-record register
//! at B5:D10 with a title above it and a footnote below.

use layout_validator::*;

fn range(r0: u32, c0: u32, r1: u32, c1: u32) -> SourceRange {
    SourceRange {
        start: SourceCoordinate { row: r0, column: c0 },
        end_exclusive: SourceCoordinate { row: r1, column: c1 },
    }
}

/// Title at B1, header at B5:D5, five records at B6:D10, footnote at B13.
fn evidence() -> OoxmlLayoutEvidence {
    OoxmlLayoutEvidence {
        window: range(0, 1, 13, 4),
        occupied_ranges: vec![
            range(0, 1, 1, 2),
            range(4, 1, 5, 4),
            range(5, 1, 6, 4),
            range(6, 1, 7, 4),
            range(7, 1, 8, 4),
            range(8, 1, 9, 4),
            range(9, 1, 10, 4),
            range(12, 1, 13, 2),
        ],
        merged_ranges: vec![],
        explicit_table_ranges: vec![],
    }
}

fn proposal(header: (u32, u32), data: Vec<(u32, u32)>, excluded: Vec<(u32, u32)>) -> ModelLayoutProposal {
    ModelLayoutProposal {
        contract: OOXML_LAYOUT_PLANNER_CONTRACT.to_string(),
        selections: vec![serde_json::from_value(serde_json::json!({
            "region_id": "t0",
            "orientation": "records_by_row",
            "source_range": {"start": {"row": 4, "column": 1},
                             "end_exclusive": {"row": 10, "column": 4}},
            "header_bands": [{"start": header.0, "end_exclusive": header.1}],
            "data_bands": data.iter().map(|(a, b)| serde_json::json!({"start": a, "end_exclusive": b})).collect::<Vec<_>>(),
        }))
        .expect("region")],
        excluded_ranges: excluded
            .into_iter()
            .map(|(row, column)| OoxmlLayoutExcludedRange {
                source_range: range(row, column, row + 1, column + 1),
                disposition: OoxmlLayoutDisposition::NonTable,
            })
            .collect(),
    }
}

fn check(proposal: ModelLayoutProposal) -> std::result::Result<(), String> {
    let decision = proposal.into_decision().map_err(|e| e.to_string())?;
    validate_ooxml_layout_planner_decision(&evidence(), &decision).map_err(|e| e.to_string())
}

#[test]
fn a_complete_classification_is_accepted() {
    assert_eq!(check(proposal((4, 5), vec![(5, 10)], vec![(0, 1), (12, 1)])), Ok(()));
}

#[test]
fn every_occupied_cell_must_be_classified_exactly_once() {
    // The footnote at B13 is left out entirely.
    assert_eq!(
        check(proposal((4, 5), vec![(5, 10)], vec![(0, 1)])),
        Err("layout proposal leaves occupied source cells unaccounted for".into())
    );
}

#[test]
fn the_primary_header_starts_at_the_region_origin() {
    assert_eq!(
        check(proposal((5, 6), vec![(6, 10)], vec![(0, 1), (12, 1)])),
        Err("primary header must start at the table origin".into())
    );
}

#[test]
fn a_data_band_may_not_contain_a_blank_record() {
    // Rows 11 and 12 are empty; a band covering them swallows blank records.
    let mut wide = proposal((4, 5), vec![(5, 13)], vec![(0, 1)]);
    wide.selections[0].source_range.end_exclusive.row = 13;
    assert_eq!(
        check(wide),
        Err("layout data band contains empty source records; split around blank gaps".into())
    );
}

#[test]
fn tables_and_classifications_never_overlap() {
    let mut twice = proposal((4, 5), vec![(5, 10)], vec![(0, 1), (12, 1)]);
    let mut second = twice.selections[0].clone();
    second.region_id = "t1".into();
    twice.selections.push(second);
    assert_eq!(
        check(twice),
        Err("overlapping layout source ranges".into())
    );
}

#[test]
fn a_header_band_must_intersect_something_populated() {
    // Row 11 is blank, so a header there selects nothing.
    let mut empty = proposal((4, 5), vec![(5, 10)], vec![(0, 1), (12, 1)]);
    empty.selections[0].header_bands.push(RecordAxisInterval { start: 10, end_exclusive: 11 });
    empty.selections[0].source_range.end_exclusive.row = 11;
    assert!(matches!(check(empty), Err(message) if message.contains("empty header or data band")));
}

#[test]
fn logical_rows_are_derived_from_the_intervals() {
    let decision = proposal((4, 5), vec![(5, 8), (8, 10)], vec![(0, 1), (12, 1)])
        .into_decision()
        .expect("compiles");
    let bands = &decision.selections[0].layout.data_bands;
    assert_eq!(bands[0].logical_row_start, 0);
    assert_eq!(bands[1].logical_row_start, 3, "the second band continues where the first stopped");
}
