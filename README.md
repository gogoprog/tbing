# tbing
Templates-based bindings and interfaces generator for C++

### Info

tbing uses libclang to extract classes and functions information and then uses pystache (mustache) to generate files. This project has been initially made to generate the bindings for the [gengine](https://github.com/gogoprog/gengine/) project.

### Example

Create and fill the rules.json file:

```json
[
    {
        "root": "mydirectory",
        "include-relative": ".",
        "include-dirs": [
        ],
        "files": [
            "*.h"
        ],
        "excluded-files": [
        ],
        "output":[
            {
                "template": "mytemplate.mustache",
                "rule": "single-file",
                "path": "generated.cpp"
            }
        ],
        "excluded-types":[
        ]
    }
]
```

Fill the template file, g.e for emscripten:

```cpp
#include <emscripten/bind.h>
using namespace emscripten;

EMSCRIPTEN_BINDINGS(my_module) {
    {{#classes}}
    class_<{{class_name}}>("{{class_name}}")
        {{#methods}}
        .function("{{method_other_name_camel_case}}", static_cast<{{{result_full_type}}} ({{class_name}}::*)({{#arguments}}{{{argument_full_type}}}{{comma}}{{/arguments}}){{method_const_qualifier}}>(&{{class_name}}::{{method_name}}))
        {{/methods}}
        ;
    {{/classes}}
}
```

Run the tbing application:
```shell
tbing your_directory
```

This will generate the 'generated.cpp' file as this:
```cpp
#include <emscripten/bind.h>
using namespace emscripten;

EMSCRIPTEN_BINDINGS(my_module) {
    class_<YourClass>("YourClass")
        .function("aMethod", &YourClass::aMethod)
        .function("anotherMethod", &YourClass::anotherMethod)
        ;
}
```

