use thiserror::Error;

#[derive(Debug, Error)]
pub enum EngineError {
    #[error("invalid ruleset: {0}")]
    InvalidRuleset(String),
    #[error("invalid game configuration: {0}")]
    InvalidGame(String),
    #[error("invalid command: {0}")]
    InvalidCommand(String),
    #[error("rule execution failed: {0}")]
    Rule(String),
    #[error("I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("Lua failed: {0}")]
    Lua(#[from] mlua::Error),
}

pub type Result<T> = std::result::Result<T, EngineError>;
