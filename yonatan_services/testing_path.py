from pathlib import Path
import sys,os

# current_path = Path(__file__).parent.is_dir()
current_path = Path(__file__).parent.resolve()
print("current_path: ", current_path)
# def get_testing_path() -> Path:
#     """
#     Returns the path to the testing directory.
#     If the directory does not exist, it creates it.
#     """
#     testing_path = Path(__file__).parent / "testing"
#     testing_path.mkdir(parents=True, exist_ok=True)
#     return testing_path

print( "testing sys")
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "../"))

print( script_dir)
print( project_root)