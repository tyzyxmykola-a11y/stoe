import re


def classify_operator_intent(text):
    """Classify operator intent as 'development' or 'conversation'.

    Returns 'development' only for unquoted whole-word mutation commands
    (fix, implement, add, edit, delete, commit, push).
    Returns 'conversation' for empty, questions/read-only status requests,
    ambiguous text, and mutation words appearing only inside quotes.
    """
    if not text or not text.strip():
        return 'conversation'

    # Define mutation commands
    mutation_commands = {'fix', 'implement', 'add', 'edit', 'delete', 'commit', 'push'}

    # Remove quoted sections (single and double quotes)
    # This handles nested quotes by removing the outermost quoted strings
    def remove_quotes(s):
        # Remove double-quoted strings
        s = re.sub(r'"[^"]*"', '', s)
        # Remove single-quoted strings
        s = re.sub(r"'[^']*'", '', s)
        return s

    # Get text without quoted parts
    unquoted_text = remove_quotes(text)

    # Check if any mutation command appears as a whole word in the unquoted text
    for cmd in mutation_commands:
        # Use word boundary matching to ensure whole-word match
        pattern = r'\b' + re.escape(cmd) + r'\b'
        if re.search(pattern, unquoted_text, re.IGNORECASE):
            return 'development'

    return 'conversation'
