package nativecontract.demo.coordinator

/**
 * Deterministic JSON encoder and strict decoder used for audit rows, the refresh
 * wire and the persisted credential blob. It deliberately avoids the platform
 * `org.json` stubs so JVM unit tests exercise the same code as the app.
 *
 * Decoding rejects duplicate object keys, trailing content and non-finite
 * numbers. Integers decode to [Long]; any fraction or exponent decodes to
 * [Double], so callers that need an exact integer can reject it.
 */
object Json {
    private const val MAX_DEPTH = 32

    fun encode(value: Any?): String = StringBuilder().also { write(it, value) }.toString()

    fun parse(text: String): Any? {
        val reader = Reader(text)
        val value = reader.value(0)
        reader.skipWhitespace()
        if (!reader.atEnd()) throw JsonFormatException("trailing content")
        return value
    }

    private fun write(out: StringBuilder, value: Any?) {
        when (value) {
            null -> out.append("null")
            is String -> quote(out, value)
            is Boolean -> out.append(value)
            is Int -> out.append(value)
            is Long -> out.append(value)
            is Map<*, *> -> {
                out.append('{')
                val entries = value.entries.map { (key, item) ->
                    (key as? String ?: throw IllegalArgumentException("JSON object keys must be strings")) to item
                }.sortedBy { it.first }
                entries.forEachIndexed { index, (key, item) ->
                    if (index > 0) out.append(',')
                    quote(out, key)
                    out.append(':')
                    write(out, item)
                }
                out.append('}')
            }
            is List<*> -> {
                out.append('[')
                value.forEachIndexed { index, item ->
                    if (index > 0) out.append(',')
                    write(out, item)
                }
                out.append(']')
            }
            else -> throw IllegalArgumentException("unsupported JSON value type ${value::class.java.name}")
        }
    }

    private fun quote(out: StringBuilder, value: String) {
        out.append('"')
        for (char in value) {
            when (char) {
                '"' -> out.append("\\\"")
                '\\' -> out.append("\\\\")
                '\n' -> out.append("\\n")
                '\r' -> out.append("\\r")
                '\t' -> out.append("\\t")
                '\b' -> out.append("\\b")
                '\u000C' -> out.append("\\f")
                else -> if (char < ' ') out.append(String.format("\\u%04x", char.code)) else out.append(char)
            }
        }
        out.append('"')
    }

    private class Reader(private val text: String) {
        private var index = 0

        fun atEnd(): Boolean = index >= text.length

        fun skipWhitespace() {
            while (index < text.length && text[index] in " \t\n\r") index++
        }

        fun value(depth: Int): Any? {
            if (depth > MAX_DEPTH) throw JsonFormatException("nesting too deep")
            skipWhitespace()
            if (atEnd()) throw JsonFormatException("unexpected end")
            return when (text[index]) {
                '{' -> objectValue(depth)
                '[' -> arrayValue(depth)
                '"' -> stringValue()
                't' -> literal("true", true)
                'f' -> literal("false", false)
                'n' -> literal("null", null)
                else -> numberValue()
            }
        }

        private fun objectValue(depth: Int): Map<String, Any?> {
            index++
            val result = LinkedHashMap<String, Any?>()
            skipWhitespace()
            if (consume('}')) return result
            while (true) {
                skipWhitespace()
                if (atEnd() || text[index] != '"') throw JsonFormatException("object key must be a string")
                val key = stringValue()
                if (result.containsKey(key)) throw JsonFormatException("duplicate object key")
                skipWhitespace()
                if (!consume(':')) throw JsonFormatException("missing colon")
                result[key] = value(depth + 1)
                skipWhitespace()
                if (consume('}')) return result
                if (!consume(',')) throw JsonFormatException("missing comma in object")
            }
        }

        private fun arrayValue(depth: Int): List<Any?> {
            index++
            val result = ArrayList<Any?>()
            skipWhitespace()
            if (consume(']')) return result
            while (true) {
                result += value(depth + 1)
                skipWhitespace()
                if (consume(']')) return result
                if (!consume(',')) throw JsonFormatException("missing comma in array")
            }
        }

        private fun stringValue(): String {
            index++
            val out = StringBuilder()
            while (true) {
                if (atEnd()) throw JsonFormatException("unterminated string")
                val char = text[index++]
                when {
                    char == '"' -> return out.toString()
                    char == '\\' -> {
                        if (atEnd()) throw JsonFormatException("unterminated escape")
                        when (val escaped = text[index++]) {
                            '"', '\\', '/' -> out.append(escaped)
                            'b' -> out.append('\b')
                            'f' -> out.append('\u000C')
                            'n' -> out.append('\n')
                            'r' -> out.append('\r')
                            't' -> out.append('\t')
                            'u' -> {
                                if (index + 4 > text.length) throw JsonFormatException("short unicode escape")
                                val code = text.substring(index, index + 4).toIntOrNull(16)
                                    ?: throw JsonFormatException("invalid unicode escape")
                                out.append(code.toChar())
                                index += 4
                            }
                            else -> throw JsonFormatException("invalid escape")
                        }
                    }
                    char < ' ' -> throw JsonFormatException("control character in string")
                    else -> out.append(char)
                }
            }
        }

        private fun literal(word: String, result: Any?): Any? {
            if (!text.startsWith(word, index)) throw JsonFormatException("invalid literal")
            index += word.length
            return result
        }

        private fun numberValue(): Any {
            val start = index
            consume('-')
            if (atEnd() || text[index] !in '0'..'9') throw JsonFormatException("invalid number")
            if (text[index] == '0') {
                index++
            } else {
                while (index < text.length && text[index] in '0'..'9') index++
            }
            var integral = true
            if (consume('.')) {
                integral = false
                if (atEnd() || text[index] !in '0'..'9') throw JsonFormatException("invalid fraction")
                while (index < text.length && text[index] in '0'..'9') index++
            }
            if (index < text.length && (text[index] == 'e' || text[index] == 'E')) {
                integral = false
                index++
                if (index < text.length && (text[index] == '+' || text[index] == '-')) index++
                if (atEnd() || text[index] !in '0'..'9') throw JsonFormatException("invalid exponent")
                while (index < text.length && text[index] in '0'..'9') index++
            }
            val token = text.substring(start, index)
            if (integral) return token.toLongOrNull() ?: throw JsonFormatException("integer outside signed 64-bit range")
            val decoded = token.toDouble()
            if (!decoded.isFinite()) throw JsonFormatException("non-finite number")
            return decoded
        }

        private fun consume(char: Char): Boolean {
            if (index < text.length && text[index] == char) {
                index++
                return true
            }
            return false
        }
    }
}

class JsonFormatException(message: String) : Exception(message)
