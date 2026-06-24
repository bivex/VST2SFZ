import unittest
import os
import sys

# Add the workspace directory to the path so we can import vst2sfz
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import vst2sfz

class TestVst2SfzEdgeCases(unittest.TestCase):

    # 1. Test note_to_midi parsing
    def test_note_to_midi_valid(self):
        # Standard notes
        self.assertEqual(vst2sfz.note_to_midi("C4"), 60)
        self.assertEqual(vst2sfz.note_to_midi("A0"), 21)
        self.assertEqual(vst2sfz.note_to_midi("G9"), 127)
        
        # Lowercase and accidentals
        self.assertEqual(vst2sfz.note_to_midi("c#4"), 61)
        self.assertEqual(vst2sfz.note_to_midi("bb3"), 58)
        self.assertEqual(vst2sfz.note_to_midi("Fsharp4"), 66)
        self.assertEqual(vst2sfz.note_to_midi("Dflat3"), 49)
        
        # Negative octaves
        self.assertEqual(vst2sfz.note_to_midi("C-1"), 0)
        self.assertEqual(vst2sfz.note_to_midi("G-1"), 7)
        
        # Raw midi number string
        self.assertEqual(vst2sfz.note_to_midi("60"), 60)
        self.assertEqual(vst2sfz.note_to_midi(72), 72)

    def test_note_to_midi_invalid(self):
        # Empty string
        with self.assertRaises(ValueError):
            vst2sfz.note_to_midi("")
        # No octave
        with self.assertRaises(ValueError):
            vst2sfz.note_to_midi("C")
        # Invalid letter
        with self.assertRaises(ValueError):
            vst2sfz.note_to_midi("H4")
        # Out-of-bounds structure
        with self.assertRaises(ValueError):
            vst2sfz.note_to_midi("C#999")
        # Text junk
        with self.assertRaises(ValueError):
            vst2sfz.note_to_midi("hello")
        # Out-of-bounds integers
        with self.assertRaises(ValueError):
            vst2sfz.note_to_midi(-1)
        with self.assertRaises(ValueError):
            vst2sfz.note_to_midi(128)
        # Out-of-bounds strings
        with self.assertRaises(ValueError):
            vst2sfz.note_to_midi("-1")
        with self.assertRaises(ValueError):
            vst2sfz.note_to_midi("128")
        # Invalid types
        with self.assertRaises(TypeError):
            vst2sfz.note_to_midi(None)
        with self.assertRaises(TypeError):
            vst2sfz.note_to_midi(60.5)
        with self.assertRaises(TypeError):
            vst2sfz.note_to_midi([60])

    # 1.5. Test midi_to_note_name
    def test_midi_to_note_name_valid(self):
        self.assertEqual(vst2sfz.midi_to_note_name(0), "C-1")
        self.assertEqual(vst2sfz.midi_to_note_name(60), "C4")
        self.assertEqual(vst2sfz.midi_to_note_name(127), "G9")
        # Test string-like integer input compatibility
        self.assertEqual(vst2sfz.midi_to_note_name("60"), "C4")
        # Test whole float values are allowed
        self.assertEqual(vst2sfz.midi_to_note_name(60.0), "C4")

    def test_midi_to_note_name_invalid(self):
        with self.assertRaises(ValueError):
            vst2sfz.midi_to_note_name(-1)
        with self.assertRaises(ValueError):
            vst2sfz.midi_to_note_name(128)
        with self.assertRaises(TypeError):
            vst2sfz.midi_to_note_name("C4")
        with self.assertRaises(TypeError):
            vst2sfz.midi_to_note_name(None)
        with self.assertRaises(TypeError):
            vst2sfz.midi_to_note_name(60.5)

    # 2. Test parse_note_range
    def test_parse_note_range_formats(self):
        # Single note
        self.assertEqual(vst2sfz.parse_note_range("C4"), [60])
        
        # Single negative octave note (previously a bug that crashed)
        self.assertEqual(vst2sfz.parse_note_range("C-1"), [0])
        self.assertEqual(vst2sfz.parse_note_range("G-1"), [7])
        
        # List of notes
        self.assertEqual(vst2sfz.parse_note_range("C4, E4, G4"), [60, 64, 67])
        
        # Range with default step=1
        self.assertEqual(vst2sfz.parse_note_range("C4-E4"), [60, 61, 62, 63, 64])
        
        # Range of negative octaves (previously matched greedily and failed)
        self.assertEqual(vst2sfz.parse_note_range("C-1-D-1"), [0, 1, 2])
        self.assertEqual(vst2sfz.parse_note_range("C-1 - D-1"), [0, 1, 2])
        
        # Range with custom step=3
        self.assertEqual(vst2sfz.parse_note_range("C4-C5", step=3), [60, 63, 66, 69, 72])
        
        # Range with spaces
        self.assertEqual(vst2sfz.parse_note_range("C3 - E3"), [48, 49, 50, 51, 52])
        
        # Raw midi number ranges
        self.assertEqual(vst2sfz.parse_note_range("60-64"), [60, 61, 62, 63, 64])
        
        # Mixed single notes and ranges
        self.assertEqual(vst2sfz.parse_note_range("C3, E3-G3, C4"), [48, 52, 53, 54, 55, 60])
        self.assertEqual(vst2sfz.parse_note_range("C-1, C0-D0, 60"), [0, 12, 13, 14, 60])

    def test_parse_note_range_inverted_and_invalid(self):
        # Inverted range (start higher than end) - should return empty list or not fail
        self.assertEqual(vst2sfz.parse_note_range("C4-C3"), [])
        
        # Invalid format range
        with self.assertRaises(ValueError):
            vst2sfz.parse_note_range("C4-invalid")
            
    def test_parse_note_range_invalid_step(self):
        with self.assertRaises(ValueError):
            vst2sfz.parse_note_range("C4-C5", step=0)
        with self.assertRaises(ValueError):
            vst2sfz.parse_note_range("C4-C5", step=-1)
        with self.assertRaises(ValueError):
            vst2sfz.parse_note_range("C4-C5", step="invalid")

    # 3. Test generate_key_zones
    def test_generate_key_zones_empty(self):
        self.assertEqual(vst2sfz.generate_key_zones([]), [])

    def test_generate_key_zones_single(self):
        # Single note must stretch across the entire MIDI range (0 to 127)
        zones = vst2sfz.generate_key_zones([60])
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["lokey"], 0)
        self.assertEqual(zones[0]["hikey"], 127)
        self.assertEqual(zones[0]["midi"], 60)

    def test_generate_key_zones_multiple(self):
        zones = vst2sfz.generate_key_zones([60, 64, 67])
        self.assertEqual(len(zones), 3)
        
        # First zone
        self.assertEqual(zones[0]["lokey"], 0)
        self.assertEqual(zones[0]["hikey"], 62)
        
        # Second zone
        self.assertEqual(zones[1]["lokey"], 63)
        self.assertEqual(zones[1]["hikey"], 65)
        
        # Third zone
        self.assertEqual(zones[2]["lokey"], 66)
        self.assertEqual(zones[2]["hikey"], 127)

    # 4. Test generate_velocity_layers
    def test_generate_velocity_layers_empty(self):
        self.assertEqual(vst2sfz.generate_velocity_layers([]), [])

    def test_generate_velocity_layers_single(self):
        # Single layer must stretch across the entire velocity range (1 to 127)
        layers = vst2sfz.generate_velocity_layers([100])
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0]["lovel"], 1)
        self.assertEqual(layers[0]["hivel"], 127)

    def test_generate_velocity_layers_multiple(self):
        layers = vst2sfz.generate_velocity_layers([40, 80, 127])
        self.assertEqual(len(layers), 3)
        
        # Low layer
        self.assertEqual(layers[0]["lovel"], 1)
        self.assertEqual(layers[0]["hivel"], 60)
        
        # Middle layer
        self.assertEqual(layers[1]["lovel"], 61)
        self.assertEqual(layers[1]["hivel"], 103)
        
        # High layer
        self.assertEqual(layers[2]["lovel"], 104)
        self.assertEqual(layers[2]["hivel"], 127)

    # 5. Test find_loop_points
    def test_find_loop_points_high_pitch(self):
        # High pitch has very small wavelength. Loop should be calculated correctly.
        l_start, l_end = vst2sfz.find_loop_points(108, 44100, 2.0, 132300) # C8 note
        self.assertIsNotNone(l_start)
        self.assertIsNotNone(l_end)
        self.assertTrue(l_end > l_start)
        self.assertTrue(l_end < 2.0 * 44100) # Must be before note-off

    def test_find_loop_points_low_pitch_short_duration_graceful_fail(self):
        # Extremely low pitch has a very long wavelength.
        # If the note duration is too short, the wavelength won't fit into the hold duration.
        # The loop points must return (None, None) gracefully instead of raising a crash/negative value.
        l_start, l_end = vst2sfz.find_loop_points(12, 96000, 0.1, 9600) # C-1 note at 96kHz, held only 0.1s
        self.assertIsNone(l_start)
        self.assertIsNone(l_end)

    def test_find_loop_points_negative_cycles_graceful_fail(self):
        # Test case where note_on_duration * sr - loop_start is less than 200 samples
        # max_length becomes negative, causing loop points to fail gracefully
        l_start, l_end = vst2sfz.find_loop_points(60, 44100, 0.501, 22100)
        self.assertIsNone(l_start)
        self.assertIsNone(l_end)

if __name__ == "__main__":
    unittest.main()
