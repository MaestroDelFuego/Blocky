#version 150

// Vertex shader
#ifdef VERTEX

uniform mat4 p3d_ModelViewProjectionMatrix;

in vec4 p3d_Vertex;
in vec4 p3d_Color;
in vec2 p3d_MultiTexCoord0;

out vec4 vertex_color;
out vec2 texcoord;

void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    vertex_color = p3d_Color;
    texcoord = p3d_MultiTexCoord0;
}

#endif

// Fragment shader
#ifdef FRAGMENT

uniform sampler2D p3d_Texture0;

in vec4 vertex_color;
in vec2 texcoord;

out vec4 fragColor;

void main() {
    vec4 tex_color = texture(p3d_Texture0, texcoord);
    fragColor = vertex_color * tex_color;
}

#endif
