import os
import subprocess
from pathlib import Path

def convert_mp3_to_wav(source_dir, output_dir):
    source_path = Path(source_dir)
    output_path = Path(output_dir)
    
    # Create output directory if it doesn't exist
    output_path.mkdir(parents=True, exist_ok=True)
    
    mp3_files = list(source_path.glob("*.mp3"))
    print(f"Found {len(mp3_files)} mp3 files in {source_dir}")
    
    for mp3_file in mp3_files:
        wav_file = output_path / (mp3_file.stem + ".wav")
        print(f"Converting {mp3_file.name} -> {wav_file.name}...")
        
        # ffmpeg command for Piper compatibility:
        # -y: overwrite output
        # -i: input file
        # -ar 22050: sample rate 22050Hz
        # -ac 1: mono
        # wav_file: output
        command = [
            "ffmpeg", "-y", "-i", str(mp3_file),
            "-ar", "22050",
            "-ac", "1",
            str(wav_file)
        ]
        
        try:
            subprocess.run(command, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            print(f"Error converting {mp3_file.name}: {e}")

if __name__ == "__main__":
    SOURCE = r"c:\PG\voice-desk-tts\vbee\audio_output"
    OUTPUT = r"c:\PG\voice-desk-tts\vbee\audio_output\wav"
    
    convert_mp3_to_wav(SOURCE, OUTPUT)
    print("\nConversion complete! WAV files are in:", OUTPUT)
