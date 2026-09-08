from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///.billing.db" # Telling SQLite to store everything in a file named billing.db

engine = create_engine(DATABASE_URL, connect_args= {"check_same_thread": False}) # Connection to the database

SessionLocal = sessionmaker(autocommit = False, autoflush = False, bind = engine) # Creates new session whenever we need one

Base = declarative_base()