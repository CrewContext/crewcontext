"""Utility functions."""  
import os  
from dotenv import load_dotenv  
  
def load_env(env_file: str = None):  
    env_file = env_file or os.path.join(os.getcwd(), ".env")  
    if os.path.exists(env_file):  
        load_dotenv(env_file) 
