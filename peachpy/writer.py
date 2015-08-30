# This file is part of Peach-Py package and is licensed under the Simplified BSD license.
#    See license.rst for the full text of the license.

active_writer = None


class AssemblyWriter:
    def __init__(self, output_path, assembly_format, input_path=None):
        if assembly_format not in {"go", "nasm", "masm", "gas"}:
            raise ValueError("Unknown assembly format: %s" % assembly_format)
        self.assembly_format = assembly_format
        self.output_path = output_path
        self.output_header = ""
        self.comment_prefix = {
            "go": "//",
            "nasm": ";",
            "masm": ";",
            "gas": "#"
        }[assembly_format]

        import peachpy
        if input_path is not None:
            header_linea = ["%s Generated by PeachPy %s from %s"
                            % (self.comment_prefix, peachpy.__version__, input_path), "", ""]
        else:
            header_linea = ["%s Generated by PeachPy %s" % (self.comment_prefix, peachpy.__version__), "", ""]

        import os
        self.output_header = os.linesep.join(header_linea)

        self.previous_writer = None

    def __enter__(self):
        global active_writer
        self.previous_writer = active_writer
        active_writer = self
        self.output_file = open(self.output_path, "w")
        self.output_file.write(self.output_header)
        self.output_file.flush()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        global active_writer
        active_writer = self.previous_writer
        self.previous_writer = None
        if exc_type is None:
            self.output_file.close()
            self.output_file = None
        else:
            import os
            os.unlink(self.output_file.name)
            self.output_file = None
            raise

    def add_function(self, function):
        import peachpy.x86_64.function
        assert isinstance(function, peachpy.x86_64.function.ABIFunction), \
            "Function must be bindinded to an ABI before its assembly can be used"

        function_code = function.format(self.assembly_format)

        import os
        self.output_file.write(function_code + os.linesep)
        self.output_file.flush()


class ELFWriter:
    def __init__(self, output_path, abi, input_path=None):
        from peachpy.formats.elf.image import Image
        from peachpy.formats.elf.section import TextSection, ReadOnlyDataSection

        self.output_path = output_path
        self.previous_writer = None
        self.abi = abi
        self.image = Image(abi, input_path)
        self.text_section = TextSection()
        self.image.add_section(self.text_section)
        self.text_rela_section = None
        self.rodata_section = None

    def __enter__(self):
        global active_writer
        self.previous_writer = active_writer
        active_writer = self
        self.output_file = open(self.output_path, "w", buffering=0)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        global active_writer
        active_writer = self.previous_writer
        self.previous_writer = None
        if exc_type is None:
            self.output_file.write(self.image.as_bytearray)
            self.output_file.close()
            self.output_file = None
        else:
            import os
            os.unlink(self.output_file.name)
            self.output_file = None
            raise

    def add_function(self, function):
        import peachpy.x86_64.function
        assert isinstance(function, peachpy.x86_64.function.ABIFunction), \
            "Function must be bindinded to an ABI before its assembly can be used"

        encoded_function = function.encode()

        function_offset = len(self.text_section.content)
        self.text_section.content += encoded_function.code_content

        function_rodata_offset = 0
        if encoded_function.const_content:
            if self.rodata_section is None:
                from peachpy.formats.elf.section import ReadOnlyDataSection
                self.rodata_section = ReadOnlyDataSection()
                self.image.add_section(self.rodata_section)
            function_rodata_offset = self.rodata_section.get_content_size(self.abi)
            self.rodata_section.content += encoded_function.const_content

        # Map from symbol name to symbol index
        from peachpy.formats.elf.symbol import Symbol, SymbolBinding, SymbolType
        symbol_map = dict()
        for symbol in encoded_function.const_symbols:
            const_symbol = Symbol()
            const_symbol.name = symbol.name
            const_symbol.value = function_rodata_offset + symbol.offset
            const_symbol.size = symbol.size
            const_symbol.section = self.rodata_section
            const_symbol.binding = SymbolBinding.local
            const_symbol.type = SymbolType.data_object
            self.image.symtab.add(const_symbol)
            symbol_map[symbol.name] = const_symbol

        if encoded_function.code_relocations:
            if self.text_rela_section is None:
                from peachpy.formats.elf.section import RelocationsWithAddendSection
                self.text_rela_section = RelocationsWithAddendSection(self.text_section, self.image.symtab)
                self.image.add_section(self.text_rela_section)

            from peachpy.formats.elf.symbol import RelocationWithAddend, RelocationType
            for relocation in encoded_function.code_relocations:
                elf_relocation = RelocationWithAddend(RelocationType.x86_64_pc32,
                                                      relocation.offset,
                                                      symbol_map[relocation.symbol],
                                                      -4)
                self.text_rela_section.add(elf_relocation)

        function_symbol = Symbol()
        function_symbol.name = function.name
        function_symbol.value = function_offset
        function_symbol.content_size = len(encoded_function.code_content)
        function_symbol.section = self.text_section
        function_symbol.binding = SymbolBinding.global_
        function_symbol.type = SymbolType.function
        self.image.symtab.add(function_symbol)


class MachOWriter:
    def __init__(self, output_path, abi):
        from peachpy.formats.macho.image import Image

        self.output_path = output_path
        self.previous_writer = None
        self.abi = abi
        self.image = Image(abi)

    def __enter__(self):
        global active_writer
        self.previous_writer = active_writer
        active_writer = self
        self.output_file = open(self.output_path, "w", buffering=0)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        global active_writer
        active_writer = self.previous_writer
        self.previous_writer = None
        if exc_type is None:
            self.output_file.write(self.image.as_bytearray)
            self.output_file.close()
            self.output_file = None
        else:
            import os
            os.unlink(self.output_file.name)
            self.output_file = None
            raise

    def add_function(self, function):
        import peachpy.x86_64.function
        assert isinstance(function, peachpy.x86_64.function.ABIFunction), \
            "Function must be bindinded to an ABI before its assembly can be used"

        encoded_function = function.encode()
        function_code = encoded_function.code_content

        function_offset = len(self.image.text_section.content)

        self.image.text_section.append(function_code)

        from peachpy.formats.macho.symbol import Symbol, SymbolDescription, SymbolType, SymbolVisibility

        function_symbol = Symbol(self.abi)
        function_symbol.description = SymbolDescription.Defined
        function_symbol.type = SymbolType.SectionRelative
        function_symbol.visibility = SymbolVisibility.External
        function_symbol.string_index = self.image.string_table.add("_" + function.name)
        function_symbol.section_index = self.image.text_section.index
        function_symbol.value = function_offset
        self.image.symbols.append(function_symbol)


class MSCOFFWriter:
    def __init__(self, output_path, abi, input_path=None):
        from peachpy.formats.mscoff.image import Image
        from peachpy.formats.mscoff.section import TextSection

        self.output_path = output_path
        self.previous_writer = None
        self.abi = abi
        self.image = Image(abi, input_path)
        self.text_section = TextSection()
        self.image.add_section(self.text_section, ".text")

    def __enter__(self):
        global active_writer
        self.previous_writer = active_writer
        active_writer = self
        self.output_file = open(self.output_path, "w", buffering=0)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        global active_writer
        active_writer = self.previous_writer
        self.previous_writer = None
        if exc_type is None:
            self.output_file.write(self.image.as_bytearray)
            self.output_file.close()
            self.output_file = None
        else:
            import os
            os.unlink(self.output_file.name)
            self.output_file = None
            raise

    def add_function(self, function):
        import peachpy.x86_64.function
        assert isinstance(function, peachpy.x86_64.function.ABIFunction), \
            "Function must be bindinded to an ABI before its assembly can be used"

        encoded_function = function.encode()
        function_code = encoded_function.code_content

        function_offset = len(self.text_section.content)
        self.text_section.write(function_code)

        from peachpy.formats.mscoff.symbol import SymbolEntry, SymbolType, StorageClass
        function_symbol = SymbolEntry()
        function_symbol.value = function_offset
        function_symbol.section_index = self.text_section.index
        function_symbol.symbol_type = SymbolType.function
        function_symbol.storage_class = StorageClass.external
        self.image.add_symbol(function_symbol, function.name)


class NullWriter:
    def __init__(self):
        pass

    def __enter__(self):
        global active_writer
        self.previous_writer = active_writer
        active_writer = None
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        global active_writer
        active_writer = self.previous_writer
        self.previous_writer = None
