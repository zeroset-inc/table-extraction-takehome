//! Compile a proposed layout and check it against the worksheet's real geometry.
//!
//!     validate --evidence cases/<case>.evidence.json --answer my-answer.json
//!
//! Exit 0: the proposal compiled and passed every geometric rule.
//! Exit 1: rejected — the message names the rule that failed.
//! Exit 2: bad usage or unreadable input.

use std::process::ExitCode;

use layout_validator::{
    ModelLayoutProposal, OoxmlLayoutDisposition, OoxmlLayoutEvidence, SourceRange, TableOrientation,
};

fn column_name(mut column: u32) -> String {
    let mut name = String::new();
    column += 1;
    while column > 0 {
        let rem = (column - 1) % 26;
        name.insert(0, (b'A' + rem as u8) as char);
        column = (column - 1) / 26;
    }
    name
}

fn a1(range: SourceRange) -> String {
    format!(
        "{}{}:{}{}",
        column_name(range.start.column),
        range.start.row + 1,
        column_name(range.end_exclusive.column - 1),
        range.end_exclusive.row
    )
}

fn arg(args: &[String], flag: &str) -> Option<String> {
    args.iter()
        .position(|a| a == flag)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

fn read<T: serde::de::DeserializeOwned>(path: &str) -> Result<T, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    serde_json::from_str(&text).map_err(|e| format!("{path}: {e}"))
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let (Some(evidence_path), Some(answer_path)) = (arg(&args, "--evidence"), arg(&args, "--answer"))
    else {
        eprintln!(
            "usage: validate --evidence <case.evidence.json> --answer <answer.json> [--quiet]\n\n\
             The evidence file states the admitted worksheet window and every occupied\n\
             rectangle. The answer file is a layout proposal: one entry per table with\n\
             intervals on the record axis, plus any explicitly excluded ranges."
        );
        return ExitCode::from(2);
    };
    let quiet = args.iter().any(|a| a == "--quiet");

    let evidence: OoxmlLayoutEvidence = match read(&evidence_path) {
        Ok(value) => value,
        Err(message) => {
            eprintln!("could not read evidence: {message}");
            return ExitCode::from(2);
        }
    };
    let proposal: ModelLayoutProposal = match read(&answer_path) {
        Ok(value) => value,
        Err(message) => {
            eprintln!("could not read answer: {message}");
            return ExitCode::from(2);
        }
    };

    let decision = match proposal.into_decision() {
        Ok(decision) => decision,
        Err(error) => {
            println!("REJECTED (compile): {error}");
            return ExitCode::FAILURE;
        }
    };

    if let Err(error) =
        layout_validator::validate_ooxml_layout_planner_decision(&evidence, &decision)
    {
        println!("REJECTED: {error}");
        return ExitCode::FAILURE;
    }

    if quiet {
        println!("ACCEPTED");
        return ExitCode::SUCCESS;
    }

    println!("ACCEPTED — {} table(s)", decision.selections.len());
    for selection in &decision.selections {
        let layout = &selection.layout;
        let axis = match layout.orientation {
            TableOrientation::RecordsByRow => "records by row",
            TableOrientation::RecordsByColumn => "records by column",
        };
        let width = match layout.orientation {
            TableOrientation::RecordsByRow => {
                layout.source_range.end_exclusive.column - layout.source_range.start.column
            }
            TableOrientation::RecordsByColumn => {
                layout.source_range.end_exclusive.row - layout.source_range.start.row
            }
        };
        println!(
            "\n  {} at {} — {}, {} field(s)",
            selection.region_id,
            a1(layout.source_range),
            axis,
            width
        );
        for (index, header) in layout.header_ranges.iter().enumerate() {
            let role = if index == 0 { "primary" } else { "repeated" };
            println!("    header  {:<12} {}", a1(*header), role);
        }
        let mut total = 0_u64;
        for band in &layout.data_bands {
            let records = match layout.orientation {
                TableOrientation::RecordsByRow => {
                    u64::from(band.source_range.end_exclusive.row - band.source_range.start.row)
                }
                TableOrientation::RecordsByColumn => u64::from(
                    band.source_range.end_exclusive.column - band.source_range.start.column,
                ),
            };
            println!(
                "    data    {:<12} logical rows {}..{}",
                a1(band.source_range),
                band.logical_row_start,
                band.logical_row_start + records
            );
            total += records;
        }
        println!("    {total} logical row(s)");
    }
    for excluded in &decision.excluded_ranges {
        let disposition = match excluded.disposition {
            OoxmlLayoutDisposition::NonTable => "non_table",
            OoxmlLayoutDisposition::Unresolved => "unresolved",
        };
        println!("\n  excluded {:<12} {}", a1(excluded.source_range), disposition);
    }
    ExitCode::SUCCESS
}
