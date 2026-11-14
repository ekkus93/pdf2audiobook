//! The bridge to the pdf2audiobook CLI, which stays the only engine (spec §2, D3).

pub mod locate;
pub mod process;

#[cfg(test)]
pub(crate) mod testing;
