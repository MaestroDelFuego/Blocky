#version 150

uniform sampler2D p3d_Texture0;

in vec4 vertex_color;
in vec2 texcoord;

out vec4 fragColor;

void main() {
    vec4 tex_color = texture(p3d_Texture0, texcoord);
    fragColor = vertex_color * tex_color;
}
