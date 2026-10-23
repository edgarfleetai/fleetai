"""Recognize unambiguous driver move voice commands without writing data."""
import re


def parse_driver_move_voice(message):
    if not isinstance(message, str) or not message.strip() or len(message) > 300:
        return None
    text = ' '.join(message.lower().replace('ё', 'е').split())
    swap = bool(re.search(r'\b(поменяй|поменять|обменяй|обменять)\b', text))
    move = bool(re.search(r'\b(переведи|перевести|переставь|переставить)\b', text))
    if not (swap or move) or (swap and move):
        return None
    codes = re.findall(r'(?<!\d)(\d{3,4})(?!\d)', text)
    if len(codes) != 2 or codes[0] == codes[1]:
        return None
    if not swap and not (re.search(r'\b(?:с|из)\s*(?:машины\s*)?\d{3,4}', text)
                         and re.search(r'\bна\s*(?:машину\s*)?\d{3,4}', text)):
        return None
    return {'kind': 'driver_swap' if swap else 'driver_move',
            'source': codes[0], 'target': codes[1], 'swap': swap,
            'requires_confirmation': True, 'writes_performed': False}
