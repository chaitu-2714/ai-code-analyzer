from analyzer.ast_parser import extract_python_ast
from analyzer.import_parser import extract_imports


def test_python_ast_extraction():
    """Verify that AST extractions catalog classes, methods, and functions correctly."""
    code = """
import os
from sys import argv

@classmethod_decorator
class User:
    def __init__(self, username):
        self.username = username

    @method_decorator
    def get_name(self):
        return self.username

@function_decorator
def calculate_age():
    return 30
"""
    result = extract_python_ast(code)

    # Verify classes
    assert len(result["classes"]) == 1
    user_cls = result["classes"][0]
    assert user_cls["name"] == "User"

    # Verify methods inside class
    methods = {m["name"] for m in user_cls["methods"]}
    assert "__init__" in methods
    assert "get_name" in methods

    # Verify standalone functions
    funcs = {f["name"] for f in result["functions"]}
    assert "calculate_age" in funcs
    assert "get_name" not in funcs  # Should be classified as a method, not standalone

def test_imports_parsing():
    """Verify that regex import extractor correctly maps external module imports."""
    py_code = """
import os
import django.db
from requests import get
"""
    js_code = """
import React, { useState } from 'react';
import axios from 'axios';
const fs = require('fs');
"""

    py_imports = extract_imports(py_code, "Python")
    js_imports = extract_imports(js_code, "JavaScript")

    assert "os" in py_imports
    assert "django" in py_imports
    assert "requests" in py_imports

    assert "react" in js_imports
    assert "axios" in js_imports
    assert "fs" in js_imports
