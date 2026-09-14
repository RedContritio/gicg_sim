// Package strictjson validates reproducibility records without JSON's permissive
// defaults (missing fields, duplicate keys, null scalars and truncated arrays).
package strictjson

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"reflect"
	"strings"
)

func Decode(data []byte, dst any) error {
	v := reflect.ValueOf(dst)
	if v.Kind() != reflect.Pointer || v.IsNil() {
		return fmt.Errorf("decode destination must be a non-nil pointer")
	}
	d := json.NewDecoder(bytes.NewReader(data))
	if err := uniqueKeys(d); err != nil {
		return err
	}
	if _, err := d.Token(); err != io.EOF {
		return fmt.Errorf("trailing JSON data")
	}
	candidate := reflect.New(v.Elem().Type())
	d = json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err := d.Decode(candidate.Interface()); err != nil {
		return err
	}
	if err := shape(data, v.Elem().Type(), "$"); err != nil {
		return err
	}
	v.Elem().Set(candidate.Elem())
	return nil
}

func uniqueKeys(d *json.Decoder) error {
	token, err := d.Token()
	if err != nil {
		return err
	}
	delim, ok := token.(json.Delim)
	if !ok {
		return nil
	}
	switch delim {
	case '{':
		seen := map[string]bool{}
		for d.More() {
			key, err := d.Token()
			if err != nil {
				return err
			}
			name, ok := key.(string)
			if !ok {
				return fmt.Errorf("non-string object key")
			}
			if seen[name] {
				return fmt.Errorf("duplicate JSON key %q", name)
			}
			seen[name] = true
			if err := uniqueKeys(d); err != nil {
				return err
			}
		}
	case '[':
		for d.More() {
			if err := uniqueKeys(d); err != nil {
				return err
			}
		}
	default:
		return fmt.Errorf("unexpected JSON delimiter")
	}
	_, err = d.Token()
	return err
}

var unmarshaler = reflect.TypeOf((*json.Unmarshaler)(nil)).Elem()

func shape(data []byte, t reflect.Type, path string) error {
	if bytes.Equal(bytes.TrimSpace(data), []byte("null")) {
		switch t.Kind() {
		case reflect.Pointer, reflect.Map, reflect.Slice, reflect.Interface:
			return nil
		}
		return fmt.Errorf("%s: null scalar/array/struct", path)
	}
	if t.Kind() == reflect.Pointer {
		return shape(data, t.Elem(), path)
	}
	// Custom wire formats (e.g. serialized RNG) validate themselves.
	if reflect.PointerTo(t).Implements(unmarshaler) {
		return nil
	}
	switch t.Kind() {
	case reflect.Struct:
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(data, &fields); err != nil {
			return err
		}
		for i := 0; i < t.NumField(); i++ {
			f := t.Field(i)
			if f.PkgPath != "" {
				continue
			}
			tag := strings.Split(f.Tag.Get("json"), ",")
			name := tag[0]
			if name == "-" {
				continue
			}
			if name == "" {
				name = f.Name
			}
			raw, ok := fields[name]
			if !ok {
				if len(tag) > 1 && tag[1] == "omitempty" {
					continue
				}
				return fmt.Errorf("%s: missing field %q", path, name)
			}
			if err := shape(raw, f.Type, path+"."+name); err != nil {
				return err
			}
			delete(fields, name)
		}
		for name := range fields {
			return fmt.Errorf("%s: unknown field %q", path, name)
		}
	case reflect.Array, reflect.Slice:
		// encoding/json represents []byte as a base64 string.
		if t.Kind() == reflect.Slice && t.Elem().Kind() == reflect.Uint8 {
			return nil
		}
		var items []json.RawMessage
		if err := json.Unmarshal(data, &items); err != nil {
			return err
		}
		if t.Kind() == reflect.Array && len(items) != t.Len() {
			return fmt.Errorf("%s: expected %d entries, got %d", path, t.Len(), len(items))
		}
		for i, item := range items {
			if err := shape(item, t.Elem(), fmt.Sprintf("%s[%d]", path, i)); err != nil {
				return err
			}
		}
	case reflect.Map:
		var entries map[string]json.RawMessage
		if err := json.Unmarshal(data, &entries); err != nil {
			return err
		}
		for k, item := range entries {
			if err := shape(item, t.Elem(), path+"."+k); err != nil {
				return err
			}
		}
	}
	return nil
}
