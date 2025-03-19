"""turning a maze into text

- `MazeTokenizerModular` is the new recommended way to do this as of 1.0.0
- legacy `TokenizationMode` enum and `MazeTokenizer` class for supporting existing code
- a whole lot of helper classes and functions

"""

from maze_dataset.tokenization.maze_tokenizer_legacy import (
	MazeTokenizer,
	TokenizationMode,
	get_tokens_up_to_path_start,
)
from maze_dataset.tokenization.modular import MazeTokenizerModular
from maze_dataset.tokenization.modular.element_base import _TokenizerElement
from maze_dataset.tokenization.modular.elements import (
	AdjListTokenizers,
	CoordTokenizers,
	EdgeGroupings,
	EdgePermuters,
	EdgeSubsets,
	PathTokenizers,
	PromptSequencers,
	StepSizes,
	StepTokenizers,
	TargetTokenizers,
)

# we don't sort alphabetically on purpose, we sort by the type
__all__ = [
	# submodules
	"all_tokenizers",
	"maze_tokenizer",
	"save_hashes",
	# legacy tokenizer
	"MazeTokenizer",
	"TokenizationMode",
	# MMT
	"MazeTokenizerModular",
	# element base
	"_TokenizerElement",
	# elements
	"PromptSequencers",
	"CoordTokenizers",
	"AdjListTokenizers",
	"EdgeGroupings",
	"EdgePermuters",
	"EdgeSubsets",
	"TargetTokenizers",
	"StepSizes",
	"StepTokenizers",
	"PathTokenizers",
	# helpers
	"get_tokens_up_to_path_start",
]
