"""
Post-processing module for cleaning translated text.
Provides extensible cleaning operations for translation output.
"""
import re
from typing import List
from abc import ABC, abstractmethod

from src.config import PLACEHOLDER_PATTERN


class PostProcessingRule(ABC):
    """Abstract base class for post-processing rules"""
    
    @abstractmethod
    def apply(self, text: str) -> str:
        """Apply the cleaning rule to the text"""
        pass
    
    @abstractmethod
    def description(self) -> str:
        """Return a description of what this rule does"""
        pass


class RemoveResidualTagPlaceholdersRule(PostProcessingRule):
    """Remove residual tag placeholders that might remain after tag restoration"""

    def apply(self, text: str) -> str:
        # Remove [id0], [id1], etc. (unified format)
        text = re.sub(PLACEHOLDER_PATTERN, '', text)

        return text

    def description(self) -> str:
        return "Remove residual tag placeholders after restoration"




class RemoveExtraWhitespaceRule(PostProcessingRule):
    """Clean up extra whitespace created by tag removal"""
    
    def apply(self, text: str) -> str:
        # Replace multiple spaces with single space
        text = re.sub(r' +', ' ', text)
        
        # Remove spaces before punctuation
        text = re.sub(r' +([.,!?;:])', r'\1', text)
        
        # Clean up line breaks
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        
        return text.strip()
    
    def description(self) -> str:
        return "Remove extra whitespace and clean punctuation spacing"


class HTMLEntityCleanupRule(PostProcessingRule):
    """Clean up HTML entities that may appear in translations"""
    
    def apply(self, text: str) -> str:
        # Replace multiple &nbsp; entities with actual non-breaking spaces
        text = re.sub(r'(&nbsp;)+', lambda m: '\u00A0' * (len(m.group()) // 6), text)
        
        # Replace other common HTML entities
        replacements = {
            '&amp;': '&',
            '&lt;': '<',
            '&gt;': '>',
            '&quot;': '"',
            '&#39;': "'",
            '&apos;': "'",
            '&mdash;': '—',
            '&ndash;': '–',
            '&hellip;': '…'
        }
        
        for entity, replacement in replacements.items():
            text = text.replace(entity, replacement)
        
        return text
    
    def description(self) -> str:
        return "Clean up HTML entities"


class PostProcessor:
    """Main post-processor that applies all registered rules"""
    
    def __init__(self):
        self.rules: List[PostProcessingRule] = []
        self._initialize_default_rules()
    
    def _initialize_default_rules(self):
        """Add default cleaning rules"""
        self.add_rule(HTMLEntityCleanupRule())
        self.add_rule(RemoveExtraWhitespaceRule())
    
    def add_rule(self, rule: PostProcessingRule):
        """Add a new post-processing rule"""
        self.rules.append(rule)
    
    def process(self, text: str, verbose: bool = False) -> str:
        """
        Apply all post-processing rules to the text
        
        Args:
            text: The text to clean
            verbose: If True, print which rules are being applied
            
        Returns:
            The cleaned text
        """
        if not text:
            return text
        
        result = text
        for rule in self.rules:
            if verbose:
                print(f"Applying: {rule.description()}")
            result = rule.apply(result)
        
        return result
    
# Create a default instance
default_post_processor = PostProcessor()


def clean_translated_text(text: str, verbose: bool = False) -> str:
    """
    Convenience function to clean translated text with default rules
    
    Args:
        text: The translated text to clean
        verbose: If True, print which rules are being applied
        
    Returns:
        The cleaned text
    """
    return default_post_processor.process(text, verbose)


def clean_residual_tag_placeholders(text: str) -> str:
    """
    Clean up any residual TAG placeholders after tag restoration
    This should be used as a final step before saving EPUB files
    
    Args:
        text: The text to clean
        
    Returns:
        The cleaned text without residual placeholders
    """
    cleaner = RemoveResidualTagPlaceholdersRule()
    return cleaner.apply(text)


if __name__ == "__main__":
    # Test the post-processor
    test_text = """
    This is a test text.
    It also has    extra   spaces and &nbsp;&nbsp; HTML entities.
    """
    
    print("Original text:")
    print(test_text)
    print("\nCleaned text:")
    print(clean_translated_text(test_text, verbose=True))
